import io, os, socket
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from database import init_db
from routes.player import router as player_router
from routes.admin  import router as admin_router

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")


def get_local_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"


def make_qr_png(url: str) -> bytes:
    import qrcode
    from qrcode.constants import ERROR_CORRECT_M
    qr = qrcode.QRCode(version=1, error_correction=ERROR_CORRECT_M,
                       box_size=10, border=4)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#1e293b", back_color="white")
    buf = io.BytesIO()
    img.save(buf)
    buf.seek(0)
    return buf.read()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    ip  = get_local_ip()
    port = os.environ.get("PORT", "8000")
    print(f"Server ready")
    print(f"  Local  : http://{ip}:{port}/")
    print(f"  Admin  : http://{ip}:{port}/admin")
    yield

app = FastAPI(title="Quiz Event", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(player_router)
app.include_router(admin_router)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
@app.get("/player.html")
def serve_player():
    return FileResponse(os.path.join(STATIC_DIR, "player.html"))


@app.get("/admin")
@app.get("/admin.html")
def serve_admin_page():
    return FileResponse(os.path.join(STATIC_DIR, "admin.html"))


# QR — uses the actual public URL so it works locally AND when deployed
@app.get("/qr")
def serve_qr(request: Request):
    base = str(request.base_url).rstrip("/") + "/"
    png  = make_qr_png(base)
    return Response(content=png, media_type="image/png",
                    headers={"Cache-Control": "no-store"})

@app.get("/health")
async def health():
    return {"status": "ok"}
