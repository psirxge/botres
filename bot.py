import os
import fitz  # PyMuPDF
import asyncio
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv
from openai import AsyncOpenAI
from config import MODELS, DEFAULT_PROMPT, user_prompts
import httpx

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

# Инициализировать бота с помощью хранилища состояний
storage = MemoryStorage()
bot = Bot(token=get_env_var('TELEGRAM_BOT_TOKEN'))
dp = Dispatcher(storage=storage)
client = AsyncOpenAI(api_key=get_env_var('OPENAI_API_KEY'))

# Сохранение выбранной модели для каждого пользователя
user_models = {}

# Изменённая функция get_main_keyboard
def get_main_keyboard():
    keyboard = [
        [KeyboardButton(text="ChatGPT 4o-mini"), KeyboardButton(text="✏️ Изменить промпт")],
        [KeyboardButton(text="🔄 Вернуть исходный промпт")]
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

def get_model_keyboard():
    keyboard = [
        [KeyboardButton(text="ChatGPT 4o-mini")]
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

@dp.message(Command('start'))
async def send_welcome(message: Message):
    await message.reply(
        "👋 Добро пожаловать в Resume Analyzer Bot!\n\n"
        "Я помогу проанализировать ваше резюме и предложу рекомендации по улучшению.\n"
        "Сначала выберите модель для анализа или настройте промпт:",
        reply_markup=get_main_keyboard()
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

@dp.message()
async def handle_message(message: Message, state: FSMContext):
    # Если пользователь выбирает модель (сообщение с текстом)
    if message.text in MODELS:
        # Сохраняем значение модели, а не отображаемый текст
        user_models[message.from_user.id] = MODELS[message.text].value
        await message.reply(
            "✅ Модель выбрана! Теперь отправьте ваше резюме (PDF):",
            reply_markup=get_main_keyboard()
        )
        return

    # Если это PDF-файл
    if message.document and message.document.mime_type == 'application/pdf':
        if message.from_user.id not in user_models:
            await message.reply(
                "❗ Сначала выберите модель для анализа:",
                reply_markup=get_model_keyboard()
            )
            return

        await message.reply("📄 Анализирую ваше резюме... Пожалуйста, подождите.")
        
        file_id = message.document.file_id
        file = await bot.get_file(file_id)
        local_file_path = f"temp_{message.from_user.id}.pdf"

        await bot.download_file(file.file_path, local_file_path)
        text = await extract_text_from_pdf(local_file_path)
        
        if text:
            # Используем выбранную модель напрямую
            selected_model = user_models[message.from_user.id]
            analysis = await analyze_resume(text, selected_model, message.from_user.id)
            
            await message.reply("📊 Результаты анализа:")
            max_length = 4096
            for i in range(0, len(analysis), max_length):
                chunk = analysis[i:i+max_length]
                await message.reply(chunk, parse_mode=None)
            
            # Получаем отредактированное резюме
            edited_resume = await edit_resume(text, selected_model, message.from_user.id)
            await message.reply("📝 Отредактированное резюме:")
            for i in range(0, len(edited_resume), max_length):
                chunk = edited_resume[i:i+max_length]
                await message.reply(chunk, parse_mode=None)
            
            await message.reply(
                "✨ Для нового анализа выберите модель:",
                reply_markup=get_model_keyboard()
            )
        else:
            await message.reply(
                "❌ Не удалось извлечь текст из PDF. Убедитесь, что PDF содержит текстовый слой."
            )
        os.remove(local_file_path)
    elif message.document:
        await message.reply("📎 Пожалуйста, отправьте резюме в формате PDF.")

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

async def analyze_resume(text: str, model: str, user_id: int) -> str:
    user_prompt = user_prompts.get(user_id, DEFAULT_PROMPT)
    # Добавляем требование отсутствия форматирующих символов
    instruction = ("Пожалуйста, выдай ответ в простом тексте без использования markdown форматирования "
                   "(без #, *, -, и т.д.).")
    prompt = f"""{user_prompt}

{instruction}

Проанализируй резюме по следующим критериям:

1. Содержание и навыки:
   - Релевантность опыта
   - Ключевые компетенции
   - Достижения и результаты

2. Структура и оформление:
   - Читаемость
   - Организация информации
   - Форматирование

3. Оптимизация под ATS:
   - Ключевые слова
   - Совместимость с системами
   - Технические аспекты

4. Общее впечатление:
   - Профессиональный имидж
   - Уникальное торговое предложение
   - Конкурентные преимущества

Проанализируй данное резюме по следующим пунктам:
1. Общие впечатления: Насколько резюме выглядит профессионально и понятно? Есть ли ошибки или странные формулировки?
2. Структура: Соответствует ли резюме стандартам? Все ли ключевые блоки (Опыт, Навыки, Образование) присутствуют?
3. Ключевые слова: Достаточно ли в резюме ключевых слов для прохождения ATS? Какие слова стоит добавить?
4. Оформление и стиль: Как можно улучшить читабельность (краткость, четкость, логика)?
5. Сравнение с успешными резюме: Какие элементы делают резюме слабым по сравнению с лучшими примерами?
6. Рекомендации по улучшению: Дай конкретные правки, переформулировки и дополнительные пункты, которые стоит добавить.

Важно: Отвечай кратко, но по существу, с конкретными примерами и улучшенными формулировками. Если находишь ошибки или слабые места — предложи исправления сразу с примерами.

Текст резюме:
{text}
"""
    try:
        if model in ["gpt-4o-mini"]:
            response = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": instruction + "\n" + user_prompt},
                    {"role": "user", "content": prompt}
                ]
            )
            return response.choices[0].message.content
        else:
            return "Неизвестная модель."
    except Exception as e:
        return f"Ошибка при анализе резюме: {e}"

async def edit_resume(text: str, model: str, user_id: int) -> str:
    user_prompt = user_prompts.get(user_id, DEFAULT_PROMPT)
    instruction = ("Пожалуйста, отправь ответ в виде простого текста без markdown форматирования "
                   "(без #, *, -, и т.д.).")
    prompt = f"""{user_prompt}

{instruction}

Отредактируй следующее резюме так, чтобы оно получило более профессиональный вид, улучшилась структура, стиль и читабельность. Сделай текст более привлекательным для работодателей:

{text}
"""
    try:
        if model in ["gpt-4o-mini"]:
            response = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": instruction + "\n" + user_prompt},
                    {"role": "user", "content": prompt}
                ]
            )
            return response.choices[0].message.content
        else:
            return "Неизвестная модель."
    except Exception as e:
        return f"Ошибка при редактировании резюме: {e}"

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())