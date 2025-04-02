import os
import django
from pydub import AudioSegment
from gtts import gTTS
from io import BytesIO
import logging
import speech_recognition as sr
import tempfile

# Set up Django settings before importing models
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ms_football_gest.settings')
django.setup()

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext
from gestion_joueurs.models import Player, Video
from gestion_joueurs.utils import get_players_by_status  # Assuming this function exists to get players by status

# Set up logging
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# Define the start command for the bot
async def start(update: Update, context: CallbackContext):
    await update.message.reply_text("Welcome! Send me a voice message or text with a status like 'pending', 'in_progress', etc.")

# Function to generate and send voice response
async def send_voice_response(update: Update, response: str):
    """Generate TTS response and send as voice message."""
    try:
        if not response.strip():
            logger.error("Error: Empty response text!")
            await update.message.reply_text("Error generating voice message. Please try again.")
            return
        
        # Generate speech from text
        tts = gTTS(text=response, lang="en")

        # Save to temp file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as temp_mp3:
            tts.save(temp_mp3.name)
            mp3_path = temp_mp3.name

        # Convert MP3 to OGG
        ogg_path = mp3_path.replace(".mp3", ".ogg")
        audio = AudioSegment.from_mp3(mp3_path)
        audio.export(ogg_path, format="ogg")

        # Ensure file is valid before sending
        if os.path.exists(ogg_path) and os.path.getsize(ogg_path) > 0:
            with open(ogg_path, "rb") as voice:
                await update.message.reply_voice(voice=voice)
                logger.info(f"Sent voice response successfully: {ogg_path}")
        else:
            logger.error("Error: Generated voice file is empty!")
            await update.message.reply_text("Error generating voice message. Please try again.")
    
    except Exception as e:
        logger.error(f"Unexpected error in voice processing: {e}")
        await update.message.reply_text("An unexpected error occurred while processing the voice message.")

# Process Text Message
async def process_text(update: Update, context: CallbackContext):
    """Handle text messages."""
    try:
        text = update.message.text.strip().lower()
        logger.info(f"Received text message: {text}")

        # Fetch players based on status
        players = await get_players_by_status(text)
        response = "\n".join(players)

        # Send voice response
        await send_voice_response(update, response)

    except Exception as e:
        logger.error(f"Error handling text message: {e}")
        await update.message.reply_text("An unexpected error occurred while processing the text message.")

# Process Voice Message
async def process_voice(update: Update, context: CallbackContext):
    """Handle voice messages."""
    try:
        logger.info("Received a voice message.")
        
        voice = update.message.voice
        file = await voice.get_file()
        audio_file_path = "voice.ogg"

        # Download and convert audio
        await file.download_to_drive(audio_file_path)
        logger.info(f"Downloaded voice message: {audio_file_path}")

        wav_file_path = "voice.wav"
        audio = AudioSegment.from_ogg(audio_file_path)
        audio.export(wav_file_path, format="wav")

        # Recognize speech
        recognizer = sr.Recognizer()
        with sr.AudioFile(wav_file_path) as source:
            audio_data = recognizer.record(source)
            text = recognizer.recognize_google(audio_data)
            logger.info(f"Recognized text from voice: '{text}'")

            await update.message.reply_text(f"Received status: {text}")

            # Fetch players based on status
            players = await get_players_by_status(text.lower())
            response = "\n".join(players)

            # Send voice response
            await send_voice_response(update, response)

    except sr.UnknownValueError:
        logger.error("Speech Recognition could not understand the audio.")
        await update.message.reply_text("Sorry, I couldn't understand the voice message.")
    except sr.RequestError as e:
        logger.error(f"Speech Recognition service error: {e}")
        await update.message.reply_text("Speech recognition service is unavailable. Try again later.")
    except Exception as e:
        logger.error(f"Unexpected error in voice processing: {e}")
        await update.message.reply_text("An unexpected error occurred while processing the voice message.")

# Set up the Telegram Bot API and application
def main():
    bot_token = "7982870671:AAFqMnSwbUasAaIoVd3gB3ySvMQAZ0mFmh8"  # Replace with your actual bot token

    # Initialize Application
    application = Application.builder().token(bot_token).build()

    # Add command and message handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.VOICE, process_voice))  # Handler for voice messages
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_text))  # Handler for text messages

    # Start the bot
    logger.info("Bot is starting...")
    application.run_polling()

if __name__ == "__main__":
    main()