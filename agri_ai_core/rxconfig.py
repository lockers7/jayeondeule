# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# Reflex 설정 파일
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
import os
import reflex as rx

# 외부 접속용 공개 호스트/포트 (미설정 시 기본값 사용)
REFLEX_PUBLIC_HOST = os.getenv("REFLEX_PUBLIC_HOST", "lockers7.iptime.org")
REFLEX_PUBLIC_PORT = int(os.getenv("REFLEX_PUBLIC_PORT", "3000"))

config = rx.Config(
    app_name="main",
    port=3000,
    backend_port=8001,
    api_url=f"http://{REFLEX_PUBLIC_HOST}:{REFLEX_PUBLIC_PORT}",
    deploy_url=f"http://{REFLEX_PUBLIC_HOST}:{REFLEX_PUBLIC_PORT}",
    db_url="sqlite:///reflex.db",
    telemetry_enabled=False,
    disable_plugins=["reflex.plugins.sitemap.SitemapPlugin"],  
)
