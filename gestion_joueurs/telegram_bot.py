import os
import django
import logging
import tempfile
import speech_recognition as sr
from pydub import AudioSegment
from gtts import gTTS
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext
from gestion_joueurs.utils import get_players_by_status, get_payment_details, search_players

# Django settings
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ms_football_gest.settings')
django.setup()

# Logging
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# Store pending player selections
pending_player_selections = {}

def get_text_language(text: str) -> str:
    """Detects whether the input text is in French (facture) or English (status request)."""
    return "fr" if "facture" in text else "en"

async def process_request(text: str) -> str:
    """Handles both video status and payment status requests."""
    try:
        text = text.strip().lower()
        language = get_text_language(text)
        logger.info(f"Processing {language} request: {text}")
        
        if language == "fr":
            player_name = text.replace("facture", "").strip()
            return await get_payment_details(player_name) or f"Aucun détail de paiement trouvé pour '{player_name}'."
        else:
            return "Veuillez préciser un statut de vidéo (e.g., 'pending', 'completed')." if text == "video status" else "\n".join(await get_players_by_status(text)) or "No relevant data found."
    except Exception as e:
        logger.error(f"Error processing request: {e}")
        return "An unexpected error occurred while processing the request."

async def send_voice_response(update: Update, response: str):
    """Converts text to voice and sends as a response."""
    try:
        if not response.strip():
            await update.message.reply_text("Error generating voice message. Please try again.")
            return
        
        tts = gTTS(text=response, lang="en")
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as temp_mp3:
            tts.save(temp_mp3.name)
            audio = AudioSegment.from_mp3(temp_mp3.name)
            ogg_path = temp_mp3.name.replace(".mp3", ".ogg")
            audio.export(ogg_path, format="ogg")
        
        with open(ogg_path, "rb") as voice:
            await update.message.reply_voice(voice=voice)
    except Exception as e:
        logger.error(f"Unexpected error in voice processing: {e}")
        await update.message.reply_text("An error occurred while generating the voice message.")

async def process_text(update: Update, context: CallbackContext):
    """Handles text messages for invoice and status queries."""
    text = update.message.text.strip().lower()
    user_id = update.message.from_user.id
    
    if user_id in pending_player_selections:
        response = await get_payment_details(text)
        del pending_player_selections[user_id]
    else:
        response = await process_request(text)
    
    await update.message.reply_text(response)
    await send_voice_response(update, response)

async def process_voice(update: Update, context: CallbackContext):
    """Handles voice messages by converting them to text and processing the request."""
    try:
        file = await update.message.voice.get_file()
        audio_path = "voice.ogg"
        await file.download_to_drive(audio_path)
        
        audio = AudioSegment.from_ogg(audio_path)
        audio.export("voice.wav", format="wav")
        recognizer = sr.Recognizer()
        with sr.AudioFile("voice.wav") as source:
            audio_data = recognizer.record(source)
            text = recognizer.recognize_google(audio_data, language="fr-FR" if "facture" in audio_data else "en-US").lower().strip()
        
        await process_text(update, context)
    except sr.UnknownValueError:
        await update.message.reply_text("Désolé, je n'ai pas compris le message vocal.")
    except sr.RequestError as e:
        logger.error(f"Speech recognition error: {e}")
        await update.message.reply_text("Service de reconnaissance vocale indisponible. Réessayez plus tard.")

async def start(update: Update, context: CallbackContext):
    """Displays a welcome message with available options."""
    keyboard = [["Video Status"], ["Payment Status"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    
    await update.message.reply_text(
        "Welcome! Please choose an option:\n\n"
        "🎥 *Video Status*: Check the status of players' videos.\n"
        "💰 *Payment Status*: Check a player's payment details.\n\n"
        "Simply type or send a voice message with your choice!",
        reply_markup=reply_markup,
    )

def main():
    bot_token = "YOUR_BOT_TOKEN_HERE"  # Replace with your actual bot token
    application = Application.builder().token(bot_token).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_text))
    application.add_handler(MessageHandler(filters.VOICE, process_voice))
    
    logger.info("Bot is starting...")
    application.run_polling()

if __name__ == "__main__":
    main()