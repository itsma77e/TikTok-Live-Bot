import logging
import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from bot.bot_manager import BotManager
from web.routes import router, init_routes

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

app = FastAPI(title="TikTok Speech Bot")

bot_manager = BotManager()
init_routes(bot_manager)

app.include_router(router)
app.mount("/static", StaticFiles(directory="web/static"), name="static")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
