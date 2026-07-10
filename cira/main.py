from dotenv import load_dotenv

load_dotenv()

from ui.app import demo

if __name__ == "__main__":
    demo.launch()
