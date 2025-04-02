import subprocess
import sys
import os

def check_python_version() -> bool:
    """Проверка, что версия Python 3.8 или выше"""
    return sys.version_info >= (3, 8)

requirements = [
    "python-dotenv==1.0.0",
    "aiogram==3.4.1",
    "PyMuPDF==1.23.26",
    "openai==1.12.0"
]

def install_requirements() -> None:
    """Установка необходимых библиотек через pip"""
    for package in requirements:
        print(f"Installing {package}...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", package])
        except subprocess.CalledProcessError as e:
            print(f"Error installing {package}: {e}")
            sys.exit(1)
    print("Все библиотеки успешно установлены!")

def create_env_file() -> None:
    """Создать файл .env, если его не существует"""
    env_path = os.path.join(os.path.dirname(__file__), '.env')
    if not os.path.exists(env_path):
        with open(env_path, "w", encoding="utf-8") as f:
            f.write('TELEGRAM_BOT_TOKEN="your_telegram_bot_token"\n')
            f.write('OPENAI_API_KEY="your_openai_api_key"\n')
            f.write('GIGACHAT_API_PERS="your_gigachat_api_pers"\n')
        print("Создан файл .env. Обновите его значениями API ключей.")

def main():
    if not check_python_version():
        print("Требуется Python версии 3.8 или выше.")
        sys.exit(1)
    
    print("Устанавливаю необходимые библиотеки...")
    install_requirements()
    create_env_file()
    print("\nSetup завершён успешно!")
    print("Запустите бота командой: python bot.py")

if __name__ == "__main__":
    main()