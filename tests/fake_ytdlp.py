# Fake yt-dlp used only by unit tests. Mimics: -J, --version, and downloading with progress lines.
import json, os, sys, time

a = sys.argv[1:]
url = a[-1] if a else ""
if "--version" in a:
    print("2099.01.01"); sys.exit(0)
if "-J" in a:
    if "fail" in url:
        sys.stderr.write("ERROR: [youtube] x: Video unavailable\n"); sys.exit(1)
    if "playlist" in url:
        print(json.dumps({"_type": "playlist", "title": "PL", "uploader": "U", "entries": [
            {"id": "aaa", "url": "https://www.youtube.com/watch?v=aaa", "title": "One", "duration": 10},
            {"id": "bbb", "title": "Two"}]}))
    else:
        print(json.dumps({"title": "Vid", "webpage_url": url, "duration": 65, "uploader": "Me", "thumbnail": "http://t/x.jpg",
            "formats": [
                {"format_id": "140", "vcodec": "none", "acodec": "mp4a", "filesize": 3000000},
                {"format_id": "137", "vcodec": "avc1", "height": 1080, "filesize": 50000000},
                {"format_id": "136", "vcodec": "avc1", "height": 720, "filesize": 20000000},
                {"format_id": "sb0", "vcodec": "none", "acodec": "none"}]}))
    sys.exit(0)
if "fail" in url:
    sys.stderr.write("ERROR: [youtube] x: Video unavailable\n"); sys.stderr.flush(); sys.exit(1)
out = a[a.index("-o") + 1].replace("%%", "%")
ext = (a[a.index("--audio-format") + 1] if "-x" in a else "mp4")
path = out.replace("%(ext)s", ext)
delay = float(os.environ.get("FAKE_DELAY", "0.02"))
for i in range(1, 11):
    print(f"MYVDP|{i * 100}|1000|NA|2097152|{10 - i}", flush=True)
    time.sleep(delay)
print("[Merger] Merging formats", flush=True)
open(path, "wb").write(b"x" * 2048)
sys.exit(0)
