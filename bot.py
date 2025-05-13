import os
import fitz  # PyMuPDF
import asyncio
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv
from config import MODELS, DEFAULT_PROMPT, user_prompts
import re
from openai import ChatCompletion  # Импортируем OpenAI SDK
import openai

logging.basicConfig(level=logging.INFO)

class PromptStates(StatesGroup):
    waiting_for_prompt = State()

load_dotenv()

# Убираем кавычки из переменных окружения, если они есть
def get_env_var(key: str) -> str:
    value = os.getenv(key)
    if value:
        return value.strip('"')
    return ""

# Устанавливаем API-ключ OpenAI
openai.api_key = get_env_var('OPENAI_API_KEY')

# Инициализировать бота с помощью хранилища состояний
storage = MemoryStorage()
bot = Bot(token=get_env_var('TELEGRAM_BOT_TOKEN'))
dp = Dispatcher(storage=storage)

# Сохранение выбранной модели для каждого пользователя
user_models = {}

# Глобальный словарь для хранения количества анализов пользователя
analysis_count = {}

# Изменённая функция get_main_keyboard
def get_main_keyboard():
    keyboard = [
 #       [KeyboardButton(text="GigaChat-2"), KeyboardButton(text="✏️ Изменить промпт")],
 #       [KeyboardButton(text="🔄 Вернуть исходный промпт")],
        [KeyboardButton(text="📖 Инструкция")]
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

def get_model_keyboard():
    keyboard = [
        [KeyboardButton(text="GigaChat-2")]
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

async def check_subscription(user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(get_env_var('CHANNEL_USERNAME'), user_id)
        return member.status in ['creator', 'administrator', 'member']
    except Exception as e:
        print(f"Ошибка при проверке подписки: {e}")
        return False

# Изменяем middleware для проверки подписки
async def subscription_middleware(handler, event, data):
    user = data["event_from_user"]

    # Всегда пропускаем команду /start и проверку подписки
    if (isinstance(event, Message) and event.text == '/start') or \
       (isinstance(event, types.CallbackQuery) and event.data == "check_subscription") or \
       (isinstance(event, Message) and event.text == "📖 Инструкция"):
        return await handler(event, data)

    # Если это первое использование - пропускаем проверку подписки
    if analysis_count.get(user.id, 0) == 0:
        return await handler(event, data)

    # Для всех последующих запросов проверяем подписку
    if not await check_subscription(user.id):
        keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="Подписаться", url=get_env_var('CHANNEL_LINK'))],
            [types.InlineKeyboardButton(text="Проверить подписку", callback_data="check_subscription")]
        ])

        if isinstance(event, types.CallbackQuery):
            await event.answer(
                "Для дальнейшего использования бота необходимо подписаться на канал.",
                show_alert=True
            )
            await event.message.reply(
                "Вы использовали бесплатный анализ. Для продолжения работы подпишитесь на наш канал.",
                reply_markup=keyboard,
                parse_mode=None
            )
        else:
            await event.answer(
                "Вы использовали бесплатный анализ. Для продолжения работы подпишитесь на наш канал.",
                reply_markup=keyboard,
                parse_mode=None
            )
        return

    return await handler(event, data)

# Регистрируем middleware
dp.message.middleware(subscription_middleware)
dp.callback_query.middleware(subscription_middleware)

# Изменяем обработчик команды /start
@dp.message(Command('start'))
async def send_welcome(message: Message):
    await message.reply(
        f"👋 Добро пожаловать в {get_env_var('BOT_NAME')}!\n\n"
        "У вас есть возможность одного бесплатного анализа резюме.\n"
        "Для дальнейшего использования потребуется подписка на канал.\n\n"
        "Отправьте ваше резюме в формате PDF для анализа.",
        reply_markup=get_main_keyboard(),
        parse_mode=None
    )

def check_subscription_filter(callback_query: types.CallbackQuery) -> bool:
    return callback_query.data == "check_subscription"

# Обновляем обработчик проверки подписки
@dp.callback_query(lambda c: c.data == "check_subscription")
async def process_check_subscription(callback_query: types.CallbackQuery):
    if await check_subscription(callback_query.from_user.id):
        await callback_query.answer("✅ Подписка подтверждена!", show_alert=True)
        await bot.send_message(
            callback_query.from_user.id,
            "Спасибо за подписку! Теперь вы можете пользоваться ботом без ограничений.\n"
            "Отправьте ваше резюме в формате PDF для анализа.",
            reply_markup=get_main_keyboard(),
            parse_mode=None
        )
    else:
        await callback_query.answer(
            "❌ Вы не подписаны. Подпишитесь на канал и повторите проверку.",
            show_alert=True
        )

@dp.message(lambda message: message.text == "✏️ Изменить промпт")
async def change_prompt(message: Message, state: FSMContext):
    current_prompt = user_prompts.get(message.from_user.id, DEFAULT_PROMPT)
    await message.reply(
        "📝 Отправьте новый промпт для анализа резюме.\n\n"
        "Текущий промпт:\n"
        f"{current_prompt}\n\n"
        "Для отмены нажмите /cancel",
        reply_markup=types.ReplyKeyboardRemove()
    )
    await state.set_state(PromptStates.waiting_for_prompt)

@dp.message(lambda message: message.text == "🔄 Вернуть исходный промпт")
async def reset_prompt(message: Message, state: FSMContext):
    user_prompts[message.from_user.id] = DEFAULT_PROMPT
    await message.reply(
        "✅ Промпт сброшен до исходного.",
        reply_markup=get_main_keyboard()
    )

@dp.message(Command("cancel"))
async def cancel_prompt(message: Message, state: FSMContext):
    await state.clear()
    await message.reply(
        "❌ Изменение промпта отменено.",
        reply_markup=get_main_keyboard()
    )

@dp.message(PromptStates.waiting_for_prompt)
async def process_prompt_change(message: Message, state: FSMContext):
    user_prompts[message.from_user.id] = message.text
    await state.clear()
    await message.reply(
        "✅ Промпт успешно обновлен!\n"
        "Теперь выберите модель для анализа или отправьте PDF файл:",
        reply_markup=get_main_keyboard()
    )

# Функция для удаления Markdown-символов, всех кроме - т.к. присутствую такие слова как что-то и т.п.
def remove_markdown(text: str) -> str:
    markdown_pattern = r"([*_~`\[\]()>#])"
    return re.sub(markdown_pattern, "", text)

@dp.message(lambda message: message.text == "📖 Инструкция")
async def show_instructions(message: Message):
    # Создаем inline клавиатуру для выбора платформы
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="💻 Windows/Mac", callback_data="instruction_pc")],
        [types.InlineKeyboardButton(text="📱 iOS", callback_data="instruction_ios")],
        [types.InlineKeyboardButton(text="📱 Android", callback_data="instruction_android")]
    ])

    await message.reply(
        "Выберите вашу платформу для получения инструкции:",
        reply_markup=keyboard,
        parse_mode=None
    )

@dp.callback_query(lambda c: c.data.startswith("instruction_"))
async def process_instruction(callback_query: types.CallbackQuery):
    platform = callback_query.data.split("_")[1]

    instructions = {
        "pc": {
            "text": ("Как сохранить резюме в PDF на компьютере:\n\n"
                    "1. Откройте документ в Word/Google Docs\n"
                    "2. Нажмите «Файл» → «Сохранить как» или «Экспорт»\n"
                    "3. Выберите формат PDF\n"
                    "4. Нажмите «Сохранить»\n"
                    "5. Отправьте файл боту"),
            "images": ["pc_step1.png", "pc_step2.png"]
        },
        "ios": {
            "text": ("Как сохранить резюме в PDF на iOS:\n\n"
                    "1. Откройте документ\n"
                    "2. Нажмите кнопку «Поделиться»\n"
                    "3. Выберите «Сохранить в PDF»\n"
                    "4. Отправьте файл боту"),
            "images": ["ios_step1.png", "ios_step2.png"]
        },
        "android": {
            "text": ("Как сохранить резюме в PDF на Android:\n\n"
                    "1. Откройте документ\n"
                    "2. Нажмите на три точки ⋮\n"
                    "3. Выберите «Сохранить как PDF»\n"
                    "4. Отправьте файл боту"),
            "images": ["android_step1.png", "android_step2.png"]
        }
    }

    if platform in instructions:
        # Отправляем текст инструкции
        await bot.send_message(
            callback_query.from_user.id,
            instructions[platform]["text"],
            parse_mode=None
        )

        # Отправляем изображения
        media_group = []
        for image in instructions[platform]["images"]:
            try:
                file_path = os.path.join("instructions", image)
                if os.path.exists(file_path):
                    # Создаем FSInputFile для каждого изображения
                    file = types.FSInputFile(file_path)
                    media_group.append(types.InputMediaPhoto(media=file))
            except Exception as e:
                print(f"Ошибка при подготовке изображения {image}: {e}")
                continue

        if media_group:
            try:
                await bot.send_media_group(
                    chat_id=callback_query.from_user.id,
                    media=media_group
                )
            except Exception as e:
                print(f"Ошибка при отправке изображений: {e}")
                await bot.send_message(
                    callback_query.from_user.id,
                    "Извините, не удалось загрузить изображения инструкции.",
                    parse_mode=None
                )

    await callback_query.answer()

@dp.message()
async def handle_message(message: Message, state: FSMContext):
    # Закомментировали проверку на выбор модели:
    # if message.text in MODELS:
    #     await message.reply(
    #         "✅ Модель выбрана! Теперь отправьте ваше резюме (PDF):",
    #         reply_markup=get_main_keyboard(),
    #         parse_mode=None
    #     )
    #     return

    if message.document and message.document.mime_type == 'application/pdf':
        await message.reply("📄 Анализирую ваше резюме... Пожалуйста, подождите.", parse_mode=None)

        file_id = message.document.file_id
        try:
            # Получаем информацию о файле
            file = await bot.get_file(file_id)
            local_file_path = f"temp_{message.from_user.id}.pdf"

            # Пытаемся загрузить файл
            try:
                await bot.download_file(file.file_path, local_file_path)
            except Exception as e:
                await message.reply("❌ Ошибка при загрузке файла. Попробуйте снова.", parse_mode=None)
                print(f"Ошибка при загрузке файла: {e}")
                return

            # Извлекаем текст из PDF
            text = await extract_text_from_pdf(local_file_path)

            if text:
                # Используем модель "gpt-4o-mini"
                selected_model = "gpt-4o-mini"
                analysis = await analyze_resume(text, selected_model, message.from_user.id)
                analysis = remove_markdown(analysis)

                await message.reply("📊 Результаты анализа:", parse_mode=None)
                max_length = 4096
                for i in range(0, len(analysis), max_length):
                    chunk = analysis[i:i+max_length]
                    await message.reply(chunk, parse_mode=None)

                analysis_count[message.from_user.id] = analysis_count.get(message.from_user.id, 0) + 1
            else:
                await message.reply(
                    "❌ Не удалось извлечь текст из PDF. Убедитесь, что PDF содержит текстовый слой.",
                    parse_mode=None
                )
            os.remove(local_file_path)
        except Exception as e:
            await message.reply("❌ Произошла ошибка при обработке файла. Попробуйте снова.", parse_mode=None)
            print(f"Ошибка при обработке файла: {e}")
    elif message.document:
        await message.reply("📎 Пожалуйста, отправьте резюме в формате PDF.", parse_mode=None)

async def extract_text_from_pdf(file_path: str) -> str:
    try:
        doc = fitz.open(file_path)
        text = ""
        for page in doc:
            text += page.get_text()
        return text
    except Exception as e:
        print(f"Ошибка при извлечении текста: {e}")
        return ""

# Теперь изменим функцию analyze_resume:
async def analyze_resume(text: str, model: str, user_id: int) -> str:
    user_prompt = user_prompts.get(user_id, DEFAULT_PROMPT)
    instruction = ("Пожалуйста, выдай ответ в простом тексте без использования markdown форматирования "
                   "(без #, *, -, и т.д.).")
    prompt = f"""{user_prompt}

{instruction}

{get_env_var('ANALYZE_INSTRUCTIONS')}

Текст резюме:
{text}
"""
    try:
        # Убедимся, что модель корректно проверяется
        if model == "gpt-4o-mini":
            # Используем OpenAI ChatCompletion для вызова модели
            response = await ChatCompletion.acreate(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}]
            )
            return response.choices[0].message["content"]
        else:
            # Если модель не совпадает, возвращаем сообщение об ошибке
            return f"Неизвестная модель: {model}"
    except Exception as e:
        return f"Ошибка при анализе резюме: {e}"

async def edit_resume(text: str, model: str, user_id: int) -> str:
    user_prompt = user_prompts.get(user_id, DEFAULT_PROMPT)
    instruction = ("Пожалуйста, отправь ответ в виде простого текста без markdown форматирования "
                   "(без #, *, -, и т.д.).")
    prompt = f"""{user_prompt}

{instruction}

{get_env_var('EDIT_INSTRUCTIONS')}

Текст резюме:
{text}
"""
    try:
        # Убедимся, что модель корректно проверяется
        if model == "gpt-4o-mini":
            # Используем OpenAI ChatCompletion для вызова модели
            response = await ChatCompletion.acreate(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}]
            )
            return response.choices[0].message["content"]
        else:
            # Если модель не совпадает, возвращаем сообщение об ошибке
            return f"Неизвестная модель: {model}"
    except Exception as e:
        return f"Ошибка при редактировании резюме: {e}"

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())