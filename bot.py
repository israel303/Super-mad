import logging
import os
from telegram import Update, __version__ as TG_VER
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from PIL import Image
import io
import asyncio
import re
from fastapi import FastAPI, Request, Response
from uvicorn import Config, Server
import json

# הגדרת FastAPI
app = FastAPI()

# נתיב health check עבור UptimeRobot (תמיכה ב-GET ו-HEAD)
@app.get("/health")
@app.head("/health")
async def health_check():
    return {"status": "ok"}

# נתיב Webhook של Telegram
@app.post("/{token}")
async def telegram_webhook(token: str, request: Request):
    if token != os.getenv('TELEGRAM_TOKEN'):
        logger.error("טוקן Webhook לא תקין")
        return Response(status_code=403)
    try:
        update = await request.json()
        update = Update.de_json(update, application.bot)
        await application.process_update(update)
        return Response(status_code=200)
    except Exception as e:
        logger.error(f"שגיאה בטיפול ב-Webhook: {e}")
        return Response(status_code=500)

# הגדרת לוגים
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# תמונת ה-thumbnail הקבועה
THUMBNAIL_PATH = 'thumbnail.jpg'

# כתובת בסיס ל-Webhook
BASE_URL = os.getenv('BASE_URL', 'https://groky.onrender.com')

# נתיב לקובץ המילים שיוסרו
WORDS_FILE_PATH = 'words_to_remove.txt'

# יצירת אפליקציית Telegram
token = os.getenv('TELEGRAM_TOKEN')
application = None

# רישום גרסת python-telegram-bot
logger.info(f"Using python-telegram-bot version {TG_VER}")

# פונקציה: הסרת מילים מוגדרות מראש משם הקובץ
def remove_english_words(filename: str) -> str:
    try:
        base, ext = os.path.splitext(filename)
        if not os.path.exists(WORDS_FILE_PATH):
            logger.error(f"קובץ {WORDS_FILE_PATH} לא נמצא, מחזיר שם קובץ מקורי")
            return filename
        with open(WORDS_FILE_PATH, 'r', encoding='utf-8') as f:
            words_to_remove = [line.strip() for line in f if line.strip()]
        cleaned_base = base
        for word in words_to_remove:
            pattern = re.escape(word)
            cleaned_base = re.sub(pattern, '', cleaned_base, flags=re.IGNORECASE)
        cleaned_base = re.sub(r'[_|\s]+', ' ', cleaned_base.strip())
        if not cleaned_base:
            cleaned_base = "file"
        return f"{cleaned_base}{ext}"
    except Exception as e:
        logger.error(f"שגיאה בניקוי שם קובץ: {e}")
        return filename

# פקודת /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        'היי! אני גרוקי. לא מכיר? לא נורא...\n'
        'שלח לי קובץ, ותקבל אותו עם התמונה\n'
        'צריך עזרה? הקלד /help.'
    )

# פקודת /help
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        'הנה מה שאני עושה:\n'
        '1. שלח לי כל קובץ.\n'
        '2. אני אמחק מילים מסוימות באנגלית (מוגדרות מראש) משם הקובץ, גם אם הן חלק ממילה גדולה יותר.\n'
        '3. אני אוסיף לו את התמונה של אולדטאון בטלגרם.\n'
        '4. תקבל את הקובץ בחזרה.\n'
        'יש שאלות? תתאפק.'
    )

# הכנת thumbnail
async def prepare_thumbnail() -> io.BytesIO:
    try:
        with Image.open(THUMBNAIL_PATH) as img:
            img = img.convert('RGB')
            img.thumbnail((200, 300))
            thumb_io = io.BytesIO()
            img.save(thumb_io, format='JPEG', quality=85)
            thumb_io.seek(0)
            return thumb_io
    except Exception as e:
        logger.error(f"שגיאה בהכנת thumbnail: {e}")
        return None

# טיפול בקבצים
async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    document = update.message.document
    status_message = await update.message.reply_text('קיבלתי את הקובץ, רגע אחד...')

    try:
        file_obj = await document.get_file()
        input_file = f'temp_{document.file_name}'
        await file_obj.download_to_drive(input_file)
        thumb_io = await prepare_thumbnail()
        error_message = None
        if not thumb_io:
            error_message = 'לא הצלחתי להוסיף תמונה, אבל הנה הקובץ שלך.'
        original_filename = document.file_name
        cleaned_filename = remove_english_words(original_filename)
        base, ext = os.path.splitext(cleaned_filename)
        base = base.strip()
        new_filename = f"{base.replace(' ', '_')}_OldTown{ext}"
        with open(input_file, 'rb') as f:
            await context.bot.send_document(
                chat_id=update.message.chat_id,
                document=f,
                filename=new_filename,
                thumbnail=thumb_io if thumb_io else None,
                caption=error_message or 'ספריית אולדטאון - https://t.me/OldTownBackup'
            )
        os.remove(input_file)
        await status_message.delete()  # מחיקת ההודעה
    except Exception as e:
        logger.error(f"שגיאה בטיפול בקובץ: {e}")
        await update.message.reply_text('משהו השתבש. תנסה שוב?')
        await status_message.delete()  # מחיקת ההודעה גם במקרה של שגיאה

# טיפול בשגיאות
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(f'עדכון {update} גרם לשגיאה: {context.error}')
    if update and update.message:
        await update.message.reply_text('אוי, משהו השתבש. תנסה שוב.')

# פונקציה ראשית
async def main():
    global application
    # בדיקת קובץ thumbnail
    if not os.path.exists(THUMBNAIL_PATH):
        logger.error(f"קובץ thumbnail {THUMBNAIL_PATH} לא נמצא!")
        return

    # בדיקת קובץ words_to_remove.txt
    if not os.path.exists(WORDS_FILE_PATH):
        logger.error(f"קובץ {WORDS_FILE_PATH} לא נמצא!")
        return

    # קבלת הטוקן
    token = os.getenv('TELEGRAM_TOKEN')
    if not token:
        logger.error("TELEGRAM_TOKEN לא הוגדר!")
        return

    # בניית כתובת Webhook
    webhook_url = f"{BASE_URL}/{token}"
    if not webhook_url.startswith('https://'):
        logger.error("BASE_URL חייב להתחיל ב-https://!")
        return

    # יצירת האפליקציה
    application = Application.builder().token(token).build()

    # הוספת handlers
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('help', help_command))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_file))
    application.add_error_handler(error_handler)

    # בדיקה והגדרת Webhook
    try:
        webhook_info = await application.bot.get_webhook_info()
        logger.info(f"מצב Webhook נוכחי: {webhook_info}")
        if webhook_info.url != webhook_url:
            await application.bot.set_webhook(url=webhook_url)
            logger.info(f"Webhook הוגדר מחדש לכתובת: {webhook_url}")
        else:
            logger.info(f"Webhook כבר מוגדר: {webhook_url}")
    except Exception as e:
        logger.error(f"שגיאה בבדיקה/הגדרת Webhook: {e}")
        return

    # הרצת שרת FastAPI
    port = int(os.getenv('PORT', 8443))
    uvicorn_config = Config(app=app, host='0.0.0.0', port=port)
    uvicorn_server = Server(uvicorn_config)

    try:
        await application.initialize()
        await application.start()
        logger.info(f"הבוט ו-FastAPI רצים על פורט {port}")
        await uvicorn_server.serve()
    except Exception as e:
        logger.error(f"שגיאה בלולאה הראשית: {e}")
        raise
    finally:
        await application.stop()
        await application.shutdown()
        await uvicorn_server.close()
        logger.info("הבוט ו-FastAPI נסגרו")

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("הבוט נעצר על ידי המשתמש")
    except Exception as e:
        logger.error(f"שגיאה קריטית: {e}")