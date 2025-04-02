import os
import django
from pydub import AudioSegment
from gtts import gTTS
import logging
import speech_recognition as sr
import tempfile

# Set up Django settings before importing models
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ms_football_gest.settings')
django.setup()

from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext
from gestion_joueurs.utils import get_players_by_status, get_payment_details,search_players

# Set up logging
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# Start Command - Shows options
async def start(update: Update, context: CallbackContext):
    """Send a welcome message with two choices."""
    keyboard = [["Video Status"], ["Payment Status"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)

    await update.message.reply_text(
        "Welcome! Please choose an option:\n\n"
        "🎥 *Video Status*: Check the status of players' videos.\n"
        "💰 *Payment Status*: Check a player's payment details.\n\n"
        "Simply type or send a voice message with your choice!",
        reply_markup=reply_markup,
    )

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

        # Send voice response
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

# Process Text and Voice Messages
async def process_request(text: str) -> str:
    """Handles both video status and payment status requests based on input."""
    try:
        text = text.strip().lower()
        logger.info(f"Processing request: {text}")

        if text == "video status":
            return "Please type a video status (e.g., 'pending', 'completed')."

        if text == "payment status":
            return "Please type the player's name followed by 'money' (e.g., 'Richard money')."

        if "money" in text:
            player_name = text.replace("money", "").strip()
            logger.info(f"Fetching payment details for player: {player_name}")
            response = await get_payment_details(player_name)
        else:
            players = await get_players_by_status(text)
            response = "\n".join(players)

        return response if response else "No relevant data found."

    except Exception as e:
        logger.error(f"Error processing request: {e}")
        return "An unexpected error occurred while processing the request."

# Store ongoing player selections
pending_player_selections = {}

async def process_text(update: Update, context: CallbackContext):
    """Handle text interactions, including player search and invoice details."""
    text = update.message.text.strip().lower()
    user_id = update.message.from_user.id

    if user_id in pending_player_selections:
        # User is selecting from player suggestions
        selected_player = text
        del pending_player_selections[user_id]  # Remove from pending selections
        
        response = await get_payment_details(selected_player)
        await update.message.reply_text(response)
        await send_voice_response(update, response)
        return

    if "money" in text:
        player_name = text.replace("money", "").strip()
        possible_players = await search_players(player_name)

        if not possible_players:
            await update.message.reply_text(f"No players found with the name '{player_name}'. Try again.")
            return

        if len(possible_players) == 1:
            # If only one match, fetch details directly
            response = await get_payment_details(possible_players[0])
            await update.message.reply_text(response)
            await send_voice_response(update, response)
        else:
            # If multiple matches, let the user choose
            pending_player_selections[user_id] = possible_players
            keyboard = [[name] for name in possible_players]  # Convert list into keyboard format
            reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)

            await update.message.reply_text(
                "Multiple players found. Please select one:",
                reply_markup=reply_markup
            )
    else:
        response = await process_request(text)
        await update.message.reply_text(response)
        await send_voice_response(update, response)

# Process Voice Messages
async def process_voice(update: Update, context: CallbackContext):
    """Convert voice to text and process the request."""
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
            text = recognizer.recognize_google(audio_data).lower().strip()
            logger.info(f"Recognized text from voice: '{text}'")

        user_id = update.message.from_user.id

        if "money" in text:
            player_name = text.replace("money", "").strip()
            possible_players = await search_players(player_name)

            if not possible_players:
                await update.message.reply_text(f"No players found with the name '{player_name}'. Try again.")
                return

            if len(possible_players) == 1:
                response = await get_payment_details(possible_players[0])
                await update.message.reply_text(response)
                await send_voice_response(update, response)
            else:
                pending_player_selections[user_id] = possible_players
                keyboard = [[name] for name in possible_players]
                reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
                await update.message.reply_text("Multiple players found. Please select one:", reply_markup=reply_markup)
        else:
            response = await process_request(text)
            await update.message.reply_text(response)
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
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_text))  # Handles text messages
    application.add_handler(MessageHandler(filters.VOICE, process_voice))  # Handles voice messages

    # Start the bot
    logger.info("Bot is starting...")
    application.run_polling()

if __name__ == "__main__":
    main()