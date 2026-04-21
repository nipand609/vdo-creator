from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
import subprocess, uuid, shutil, json, asyncio, time, random
from pathlib import Path

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

UPLOAD_DIR = Path("uploads")
OUTPUT_DIR = Path("outputs")
UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

FILE_TTL_SECONDS = 24 * 60 * 60

async def auto_cleanup():
    while True:
        await asyncio.sleep(3600)
        now = time.time()
        for folder in [UPLOAD_DIR, OUTPUT_DIR]:
            for f in folder.iterdir():
                try:
                    age = now - f.stat().st_mtime
                    if age > FILE_TTL_SECONDS:
                        f.unlink() if f.is_file() else shutil.rmtree(f, ignore_errors=True)
                except:
                    pass

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(auto_cleanup())

app.mount("/outputs", StaticFiles(directory="outputs"), name="outputs")

@app.get("/")
async def root():
    return FileResponse("templates/index.html")

@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    ext = Path(file.filename).suffix.lower()
    allowed = {".mp4",".mov",".avi",".mkv",".webm",".jpg",".jpeg",".png",".webp",".mp3",".wav",".m4a"}
    if ext not in allowed:
        raise HTTPException(400, "ไฟล์ไม่รองรับ")
    file_id = str(uuid.uuid4())
    save_path = UPLOAD_DIR / f"{file_id}{ext}"
    with open(save_path, "wb") as f:
        shutil.copyfileobj(file.file, f)
    duration = None
    if ext in {".mp4",".mov",".avi",".mkv",".webm"}:
        try:
            r = subprocess.run(
                ["ffprobe","-v","quiet","-print_format","json","-show_streams",str(save_path)],
                capture_output=True, text=True
            )
            for s in json.loads(r.stdout).get("streams",[]):
                if s.get("codec_type") == "video":
                    duration = float(s.get("duration", 0))
                    break
        except:
            pass
    return {"id": file_id, "filename": file.filename, "ext": ext, "duration": duration}

PATTERNS = [
    ["A","B","A","B","A"],
    ["A","B","B","A","B"],
    ["A","A","B","A","B"],
    ["A","B","A","B","B"],
    ["B","A","B","A","A"],
    ["A","B","B","B","A"],
]

def smart_distribute(a_clips, b_clips, n_outputs, clips_per_output):
    a_pool = list(a_clips)
    b_pool = list(b_clips)
    random.shuffle(a_pool)
    random.shuffle(b_pool)
    pats = PATTERNS.copy()
    random.shuffle(pats)
    outputs = []
    a_idx = 0
    b_idx = 0
    for out_i in range(n_outputs):
        pat = pats[out_i % len(pats)]
        shift = out_i % len(pat)
        pat = pat[shift:] + pat[:shift]
        seq = []
        for role in pat[:clips_per_output]:
            if role == "A":
                seq.append({**a_pool[a_idx % len(a_pool)], "role": "A"})
                a_idx += 1
                if a_idx % len(a_pool) == 0:
                    random.shuffle(a_pool)
            else:
                seq.append({**b_pool[b_idx % len(b_pool)], "role": "B"})
                b_idx += 1
                if b_idx % len(b_pool) == 0:
                    random.shuffle(b_pool)
        outputs.append(seq)
    return outputs

@app.post("/plan")
async def plan(payload: dict):
    a_clips = payload.get("a_clips", [])
    b_clips = payload.get("b_clips", [])
    n_outputs = int(payload.get("n_outputs", 5))
    clips_per_output = int(payload.get("clips_per_output", 5))
    if not a_clips or not b_clips:
        raise HTTPException(400, "ต้องมีคลิป A และ B")
    sequences = smart_distribute(a_clips, b_clips, n_outputs, clips_per_output)
    return {"sequences": sequences}

jobs = {}

@app.post("/render-batch")
async def render_batch(background_tasks: BackgroundTasks, payload: dict):
    batch_id = str(uuid.uuid4())
    total = len(payload.get("outputs", []))
    jobs[batch_id] = {"status": "processing", "total": total, "done": 0, "progress": 0, "results": [], "current_label": "เริ่มต้น..."}
    background_tasks.add_task(do_batch_render, payload, batch_id)
    return {"batch_id": batch_id}

async def do_batch_render(payload, batch_id):
    outputs = payload.get("outputs", [])
    total = len(outputs)
    results = []
    for i, out_cfg in enumerate(outputs):
        job_id = str(uuid.uuid4())
        output_path = OUTPUT_DIR / f"{job_id}.mp4"
        jobs[batch_id]["current_label"] = f"กำลัง render วิดีโอที่ {i+1} จาก {total}..."
        try:
            await asyncio.get_event_loop().run_in_executor(None, render_single, out_cfg, str(output_path))
            results.append({"index": i+1, "status": "done", "url": f"/outputs/{job_id}.mp4"})
        except Exception as e:
            results.append({"index": i+1, "status": "error", "message": str(e)})
        jobs[batch_id]["done"] = i + 1
        jobs[batch_id]["progress"] = int((i+1)/total*100)
        jobs[batch_id]["results"] = list(results)
    jobs[batch_id]["status"] = "done"

def run_ff(cmd):
    """รัน ffmpeg แล้ว return True ถ้าสำเร็จ"""
    r = subprocess.run(cmd, capture_output=True)
    return r.returncode == 0

def file_ok(p):
    p = Path(p)
    return p.exists() and p.stat().st_size > 5000

def render_single(out_cfg, output_path_str):
    clips = out_cfg.get("clips", [])
    cover = out_cfg.get("cover")
    audio = out_cfg.get("audio")
    output_path = Path(output_path_str)
    tmp = UPLOAD_DIR / f"tmp_{uuid.uuid4().hex}"
    tmp.mkdir(exist_ok=True)

    try:
        # STEP 1: re-encode คลิปทุกตัวให้ได้ format เดียวกัน
        # บังคับ audio stream ด้วย anullsrc เพื่อป้องกัน concat ล้มเหลว
        processed = []
        for i, clip in enumerate(clips):
            inp = UPLOAD_DIR / f"{clip['id']}{clip['ext']}"
            if not inp.exists():
                continue
            out = tmp / f"clip_{i:03d}.mp4"

            # ลองใส่เสียง silent ก่อน (รองรับทั้งคลิปมีและไม่มีเสียง)
            ok = run_ff([
                "ffmpeg","-y",
                "-i", str(inp),
                "-f","lavfi","-i","anullsrc=r=44100:cl=stereo",
                "-vf","scale=1080:1920:force_original_aspect_ratio=decrease,"
                     "pad=1080:1920:(ow-iw)/2:(oh-ih)/2,fps=30",
                "-c:v","libx264","-preset","fast","-crf","23","-pix_fmt","yuv420p",
                "-c:a","aac","-ar","44100","-ac","2",
                "-filter_complex","[0:a][1:a]amix=inputs=2:duration=first[aout]",
                "-map","0:v","-map","[aout]",
                "-shortest", str(out)
            ])

            if not file_ok(out):
                # fallback: ไม่มีเสียงในคลิปเลย ใช้ silent track
                run_ff([
                    "ffmpeg","-y",
                    "-i", str(inp),
                    "-f","lavfi","-i","anullsrc=r=44100:cl=stereo",
                    "-vf","scale=1080:1920:force_original_aspect_ratio=decrease,"
                         "pad=1080:1920:(ow-iw)/2:(oh-ih)/2,fps=30",
                    "-c:v","libx264","-preset","fast","-crf","23","-pix_fmt","yuv420p",
                    "-c:a","aac","-ar","44100","-ac","2",
                    "-map","0:v","-map","1:a",
                    "-shortest", str(out)
                ])

            if file_ok(out):
                processed.append(out)

        if not processed:
            raise Exception("ไม่มีคลิปที่ process สำเร็จ")

        # STEP 2: concat คลิป
        cl = tmp / "concat.txt"
        concat_out = tmp / "concat.mp4"
        with open(cl,"w") as f:
            for p in processed:
                f.write(f"file '{p.resolve()}'\n")
        run_ff(["ffmpeg","-y","-f","concat","-safe","0","-i",str(cl),"-c","copy",str(concat_out)])

        if not file_ok(concat_out):
            raise Exception("concat ล้มเหลว")

        final = concat_out

        # STEP 3: ใส่ปก 3 วิ ต่อหน้า
        if cover:
            cover_path = UPLOAD_DIR / f"{cover['id']}{cover['ext']}"
            if cover_path.exists():
                cover_vid = tmp / "cover.mp4"
                run_ff([
                    "ffmpeg","-y",
                    "-loop","1","-i",str(cover_path),
                    "-f","lavfi","-i","anullsrc=r=44100:cl=stereo",
                    "-vf","scale=1080:1920:force_original_aspect_ratio=decrease,"
                         "pad=1080:1920:(ow-iw)/2:(oh-ih)/2,fps=30",
                    "-c:v","libx264","-preset","fast","-pix_fmt","yuv420p",
                    "-c:a","aac","-ar","44100","-ac","2",
                    "-t","3","-map","0:v","-map","1:a", str(cover_vid)
                ])
                if file_ok(cover_vid):
                    ccl = tmp / "cc.txt"
                    with_cover = tmp / "with_cover.mp4"
                    with open(ccl,"w") as f:
                        f.write(f"file '{cover_vid.resolve()}'\n")
                        f.write(f"file '{concat_out.resolve()}'\n")
                    run_ff(["ffmpeg","-y","-f","concat","-safe","0","-i",str(ccl),"-c","copy",str(with_cover)])
                    if file_ok(with_cover):
                        final = with_cover

        # STEP 4: ใส่เสียงพากย์ (พากย์ดัง คลิปเบา)
        if audio:
            audio_path = UPLOAD_DIR / f"{audio['id']}{audio['ext']}"
            if audio_path.exists():
                ok = run_ff([
                    "ffmpeg","-y",
                    "-i", str(final),
                    "-i", str(audio_path),
                    "-filter_complex",
                    "[0:a]volume=0.2[va];[1:a]volume=1.0[vb];[va][vb]amix=inputs=2:duration=first[aout]",
                    "-map","0:v","-map","[aout]",
                    "-c:v","copy","-c:a","aac","-ar","44100","-ac","2",
                    "-shortest", str(output_path)
                ])
                if file_ok(output_path):
                    return
                # fallback: ใช้เสียงพากย์อย่างเดียว
                run_ff([
                    "ffmpeg","-y","-i",str(final),"-i",str(audio_path),
                    "-map","0:v","-map","1:a",
                    "-c:v","copy","-c:a","aac","-shortest", str(output_path)
                ])
                if file_ok(output_path):
                    return

        shutil.copy(str(final), str(output_path))

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

@app.get("/status/{batch_id}")
async def status(batch_id: str):
    return jobs.get(batch_id, {"status": "not_found"})
