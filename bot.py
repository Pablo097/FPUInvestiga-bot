from google.oauth2 import service_account
import gspread, json, os, re

import logging
from typing import Optional, Tuple
from telegram import Chat, ChatMember, ChatMemberUpdated, Update, ChatJoinRequest
from telegram.constants import ParseMode
from telegram.helpers import escape_markdown
from telegram.error import Forbidden
from telegram.ext import (Application, ChatMemberHandler, ChatJoinRequestHandler,
                          CommandHandler, ContextTypes, MessageHandler, filters,
                          ConversationHandler)

# Telegram bot token from BotFather
TOKEN = os.environ["TOKEN"]
PORT = int(os.environ.get('PORT', '8443'))
NAME = 'fpuinvestiga-bot'
# GSheet Key for 'Lista de socios 2024 actualizada automáticamente'
SHEET_KEY = os.environ["SHEET_KEY"]
# GSheet Key for 'Lista de socios 2023 actualizada automáticamente'
SHEET_KEY_OLD = os.environ.get("SHEET_KEY_OLD", None)
# Relevant columns from the Google Sheet
gs_col_number = {'name': 1, 'phone': 2, 'dni': 3, 'birthdate': 4,
                'FPUyear': 5, 'institution': 6, 'email': 11, 'username':12}

# Import Google service account credentials
google_json = os.environ["GOOGLE_JSON"]
service_account_info = json.loads(google_json)
credentials = service_account.Credentials.from_service_account_info(service_account_info)
scope = ['https://www.googleapis.com/auth/spreadsheets.readonly']
creds_with_scope = credentials.with_scopes(scope)
# Authorize access to Google Sheets
gs_client = gspread.authorize(creds_with_scope)

# Enable logging
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                    level=logging.INFO)
# set higher logging level for httpx to avoid all GET and POST requests being logged
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

DNI = range(1)

def extract_status_change(chat_member_update: ChatMemberUpdated) -> Optional[Tuple[bool, bool]]:
    """Takes a ChatMemberUpdated instance and extracts whether the 'old_chat_member' was a member
    of the chat and whether the 'new_chat_member' is a member of the chat. Returns None, if
    the status didn't change.
    """
    status_change = chat_member_update.difference().get("status")
    old_is_member, new_is_member = chat_member_update.difference().get("is_member", (None, None))

    if status_change is None:
        return None

    old_status, new_status = status_change
    was_member = old_status in [
        ChatMember.MEMBER,
        ChatMember.OWNER,
        ChatMember.ADMINISTRATOR,
    ] or (old_status == ChatMember.RESTRICTED and old_is_member is True)
    is_member = new_status in [
        ChatMember.MEMBER,
        ChatMember.OWNER,
        ChatMember.ADMINISTRATOR,
    ] or (new_status == ChatMember.RESTRICTED and new_is_member is True)

    return was_member, is_member

async def greet_chat_members(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Greets new users in chats and announces when someone leaves"""
    result = extract_status_change(update.chat_member)
    if result is None:
        return

    was_member, is_member = result
    member_name = update.chat_member.new_chat_member.user.mention_html()

    if not was_member and is_member:
        await update.effective_chat.send_message(
            f"¡Bienvenido/a al grupo, {member_name}!",
            parse_mode=ParseMode.HTML,
        )

def get_cell_with_associate_info(sheet_key, search_data, num_column=None) -> 'Cell':
    spreadsheet = gs_client.open_by_key(sheet_key)
    worksheet = spreadsheet.get_worksheet(0)

    # Regex or literal search patterns for each type of data
    # The order of definition determines the data priority when no 'num_column' is given
    search_pattern_dict = {'name': re.compile(f"^({search_data})(?!\S)(.)*$", re.I),
                           'username': re.compile(f"^(@|\S*\/)?({search_data})[ ]*$", re.I),
                           'dni': search_data,
                           'email': search_data,
                           'phone': search_data}

    cell = None
    # If column number is given, search only there
    if num_column:
        # Get key from dict
        col_name = [cname for cname, cnum in gs_col_number.items() if cnum == num_column][0]
        cell = worksheet.find(search_pattern_dict[col_name],
                                in_column=num_column, case_sensitive=False)
    # Else, search in all relevant-info columns
    else:
        for col_name in list(search_pattern_dict):
            if col_name=='name':
                # When searching for everything, also several names, or surnames-only, can be found
                cell = worksheet.findall(re.compile(f"^(.)*(?<!\S)({search_data})(?!\S)(.)*$", re.I),
                                    in_column=gs_col_number[col_name], case_sensitive=False)
                if len(cell)==1:
                    cell = cell[0]
            else:
                cell = worksheet.find(search_pattern_dict[col_name],
                                    in_column=gs_col_number[col_name], case_sensitive=False)
            if cell:
                break

    return cell

def format_info_from_sheet_row(sheet_key, num_row) -> str:
    spreadsheet = gs_client.open_by_key(sheet_key)
    worksheet = spreadsheet.get_worksheet(0)
    row_info = worksheet.row_values(num_row)

    gs_col_string = {'name': 'Nombre', 'phone': 'Teléfono', 'dni': 'DNI',
                     'birthdate': 'Fecha nacimiento', 'FPUyear': 'Convocatoria',
                     'institution': 'Institución', 'email': 'Email', 'username':'Usuario'}
    gs_col_emoji = {'name': '🧑', 'phone': '☎️', 'dni': '🪪',
                     'birthdate': '📅', 'FPUyear': '⚖️',
                     'institution': '📍', 'email': '📧', 'username':'💬'}

    text = ""
    for col in list(gs_col_string):
        num_col = gs_col_number[col]
        if num_col <= len(row_info) and row_info[num_col-1]:
            text += f"{gs_col_emoji[col]} *{gs_col_string[col]}*: "\
                    f"`{escape_markdown(row_info[num_col-1],2)}`\n"

    return text


async def handle_join_requests(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles the approval or decline of the new user joining the group"""
    request = update.chat_join_request
    is_approved = False

    name = request.from_user.first_name
    if request.from_user.last_name:
        name += ' ' + request.from_user.last_name

    text = f"¡Hola\! Has solicitado unirte al grupo *{escape_markdown(request.chat.title,2)}*\.\n"\
           f"Se trata de un chat de uso exclusivo para soci@s de FPU Investiga\.\n\n"
    text_admins = f"🆕 Una persona con nombre *{request.from_user.mention_markdown_v2()}* "

    if request.from_user.username:
        cell = get_cell_with_associate_info(context.bot_data['sheet_key'],
                                request.from_user.username, gs_col_number['username'])
        if cell:
            text += f"He encontrado tu usuario _@{escape_markdown(request.from_user.username,2)}_ en la "\
                    f"base de datos de socios activos\. Puedes entrar\. 😊"
            is_approved = True
        else:
            text += f"No tenemos asociado tu usuario _@{escape_markdown(request.from_user.username,2)}_ "\
                    f"a ningún\/a socio\/a\. "
        text_admins += f"y usuario @{escape_markdown(request.from_user.username,2)} "
    else:
        text += f"Pareces no tener nombre de usuario de Telegram\. "

    text_admins += f"ha solicitado entrar al grupo *{escape_markdown(request.chat.title,2)}*\."

    if not is_approved:
        # cell = get_cell_with_associate_info(context.bot_data['sheet_key'],
        #                                         name, gs_col_number['username'])
        # if cell:
        #     text += f"Aunque parece que tu nombre y apellidos coinciden con el usuario "\
        #             f"\(_{cell.value}_\) que introdujiste al inscribirte\.\.\. "\
        #             f"Daremos eso por bueno\.\n\n"
        # else:
        #     text += f"Tu nombre y apellidos tampoco coinciden con el usuario que "\
        #             f"introdujiste al inscribirte\. 😞\n\n"

        if request.from_user.last_name:
            cell = get_cell_with_associate_info(context.bot_data['sheet_key'],
                                                    name, gs_col_number['name'])
            if cell:
                text += f"Parece que tu nombre y apellidos \(_{escape_markdown(name, 2)}_\) sí "\
                        f"están en nuestra base de datos de socios activos\.\n\n"
            else:
                text += f"Tu nombre y apellidos tampoco aparecen en nuestra base "\
                        f"de datos de socios activos\.\n\n"
        else:
            text += f"Y tu nombre asecas no me da suficiente información "\
                    f"para buscarte en la base de datos de socios\.\n\n"

        text += f"¿Me podrías facilitar tu *DNI* \(sin guiones ni espacios\) para "\
                f"comprobar que eres socio\/a?"

    try:
        await context.bot.send_message(request.user_chat_id, text, ParseMode.MARKDOWN_V2)
        admin_message = await context.bot.send_message(str(os.environ["DEBUG_CHAT_ID"]),
                                                text_admins, ParseMode.MARKDOWN_V2)

        if is_approved:
            await request.approve()
            text_admins = f"Se le ha dado acceso debido a que su usuario está en "\
                          f"la base de datos de socios activos\.\n\n"
            text_admins += format_info_from_sheet_row(context.bot_data['sheet_key'], cell.row)
            await admin_message.reply_text(text_admins, ParseMode.MARKDOWN_V2)
            return ConversationHandler.END

    except Forbidden:
        # User has blocked the bot
        text_admins = f"⚠️ El usuario *{escape_markdown(name, 2)}* ha solicitado acceso al grupo "\
                      f"pero tiene bloqueado al bot\. Se requiere intervención humana\."
        await context.bot.send_message(str(os.environ["DEBUG_CHAT_ID"]),
                                            text_admins, ParseMode.MARKDOWN_V2)
        return ConversationHandler.END

    # await request.approve()
    # await request.decline()

    context.user_data['joining_chat_id'] = request.chat.id
    context.user_data['admin_message'] = admin_message
    return DNI

async def input_dni(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Gets the message containing the DNI of the user and checks it"""
    # Only handle responses in the private chat
    if update.effective_chat.type != Chat.PRIVATE:
        return DNI

    if not update.message.text:
        await update.message.reply_text("Por favor, escribe únicamente tu DNI sin guiones ni espacios.")
        return DNI

    match = re.search('^[0-9A-Z]+$', update.message.text.upper())
    if not match:
        await update.message.reply_text("Por favor, escribe únicamente tu DNI sin guiones ni espacios.")
        return DNI

    dni = match[0]
    spreadsheet = gs_client.open_by_key(context.bot_data['sheet_key'])
    worksheet = spreadsheet.get_worksheet(0)
    cell = worksheet.find(dni,in_column=gs_col_number['dni'])
    chat_id = context.user_data.pop('joining_chat_id')
    admin_message = context.user_data.pop('admin_message')
    if cell:
        name = worksheet.cell(cell.row, gs_col_number['name']).value
        text = f"¡Bien\! Tu DNI _{dni}_ aparece asociado a _{escape_markdown(name,2)}_ en nuestra "\
               f"lista de socios activos\.\n\nYa tienes acceso al grupo\. 😁"
        await update.effective_user.approve_join_request(chat_id)
        text_admins = f"Se le ha dado acceso ya que el DNI introducido está en "\
                      f"la base de datos de socios activos\.\n\n"
        text_admins += format_info_from_sheet_row(context.bot_data['sheet_key'], cell.row)
    else:
        text = f"Lo siento, pero tu DNI no aparece en nuestra lista de socios "\
                f"activos, así que no puedo dejarte acceder...\n\n"\
                f"Si realmente eres socio/a, esto puede deberse a que aún no se "\
                f"haya confirmado la recepción de la cuota de inscripción/renovación.\n\n"\
                f"Si has escrito mal tu DNI, puedes volver a solicitar unirte "\
                f"al grupo y volveré a ponerme en contacto contigo."
        text = escape_markdown(text, 2)
        await update.effective_user.decline_join_request(chat_id)
        text_admins = f"⛔️ Denegado\.\nEl usuario ha introducido un DNI _{dni}_ "\
                      f"que no se ha encontrado en la base de datos de socios activos\."
    await update.message.reply_text(text, ParseMode.MARKDOWN_V2)
    await admin_message.reply_text(text_admins, ParseMode.MARKDOWN_V2)

    return ConversationHandler.END

async def search_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Identifies a possible associate by any information saved about them
    in the database. Can only be used from the admins group chat."""
    if str(update.effective_chat.id)!=str(os.environ["DEBUG_CHAT_ID"]):
        return

    if not context.args:
        text = "Sintaxis incorrecta\. Uso: `/buscar <texto>`"
        await update.effective_message.reply_text(text, ParseMode.MARKDOWN_V2)
        return

    data = ' '.join(context.args)
    sheet_key = context.bot_data['sheet_key']
    cell = get_cell_with_associate_info(sheet_key, data)
    text = ""

    # Search in old GSheet, in case was a former associate
    if not cell and 'sheet_key_old' in context.bot_data:
        sheet_key = context.bot_data['sheet_key_old']
        cell = get_cell_with_associate_info(sheet_key, data)
        if cell:
            text += f"No he podido encontrar tu búsqueda en la base de datos de socios "\
                    f"actual, pero sí en la del año pasado\.\n\n"

    if not cell:
        text += f"Lo siento, no he podido encontrar `{escape_markdown(data,2)}` "\
                f"en la base de datos de socios\."
    else:
        # If 'cell' is a list of cells, then multiple associates with the same
        # name have been found
        if type(cell) is list:
            text += f"He encontrado varias personas socias que coinciden con tu búsqueda:\n\n"
            for cell_aux in cell:
                text += f"• {escape_markdown(cell_aux.value,2)}\n"
        else:
            text += f"He encontrado esa información en la ficha de este\/a socio\/a:\n\n"
            text += format_info_from_sheet_row(sheet_key, cell.row)

    await update.effective_message.reply_text(text, ParseMode.MARKDOWN_V2)

async def start_private_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Greets the user."""
    user_name = update.effective_user.full_name
    chat = update.effective_chat
    if chat.type != Chat.PRIVATE:
        return

    logger.info("%s started a private chat with the bot", user_name)

    await update.effective_message.reply_text(
        f"Hola {user_name}. Soy el bot de FPU Investiga ☺️")

async def give_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Responses with the effective chat ID of the chat from where the command
    \id is sent."""
    text = f"ID usuario: `{update.effective_user.id}`"
    if update.effective_chat.type != Chat.PRIVATE:
        text += f"\nID chat: `{update.effective_chat.id}`"
    await update.effective_message.reply_text(text, ParseMode.MARKDOWN_V2)

async def error(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log Errors caused by Updates."""
    logger.warning('Update "%s" caused error "%s"', update, context.error)


def main(webhook_flag = True) -> None:
    """Start the bot."""
    # Create the Application with my bot TOKEN
    application = Application.builder().token(TOKEN).build()

    # TODO: Make this an input of a command and make it persistent
    # https://github.com/python-telegram-bot/python-telegram-bot/wiki/Making-your-bot-persistent
    application.bot_data['sheet_key'] = SHEET_KEY
    if SHEET_KEY_OLD:
        application.bot_data['sheet_key_old'] = SHEET_KEY_OLD

    # log all errors
    application.add_error_handler(error)

    # Process /id command
    application.add_handler(CommandHandler('id', give_id))

    # Process /buscar command
    application.add_handler(CommandHandler('buscar', search_user))

    # Handle members joining/leaving chats.
    application.add_handler(ChatMemberHandler(greet_chat_members, ChatMemberHandler.CHAT_MEMBER))

    # Handle members who want to join the group
    # application.add_handler(ChatJoinRequestHandler(handle_join_requests))
    conv_handler = ConversationHandler(
        entry_points=[ChatJoinRequestHandler(handle_join_requests)],
        states={
            DNI: [MessageHandler(filters.TEXT & ~filters.COMMAND, input_dni)],
        },
        fallbacks=[],
        per_chat=False
    )

    # TODO: Hacer que el bot sepa si alguien le ha bloqueado y avisar a los admins
    application.add_handler(conv_handler)

    # Interpret any other command or text message as a start of a private chat.
    application.add_handler(MessageHandler(filters.ALL, start_private_chat))

    # Start the Bot
    # We pass 'allowed_updates' handle *all* updates including `chat_member` updates
    # To reset this, simply pass `allowed_updates=[]`
    if webhook_flag:
        application.run_webhook(
            listen='0.0.0.0',
            port=PORT,
            url_path=TOKEN,
            webhook_url=f"https://{NAME}.onrender.com/{TOKEN}",
            allowed_updates=Update.ALL_TYPES
        )
    else:
        # For local development purposes
        application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
