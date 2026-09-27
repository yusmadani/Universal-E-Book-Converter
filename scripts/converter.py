import os
import json
import subprocess
import requests
import fitz  # PyMuPDF
from bs4 import BeautifulSoup
import pytesseract
from pdf2image import convert_from_path

event_type = os.environ.get("EVENT_NAME")
payload = json.loads(os.environ.get("CLIENT_PAYLOAD", "{}"))
bot_token = os.environ.get("BOT_TOKEN")

def send_telegram_file(chat_id, file_path, caption):
    url = f"https://api.telegram.org/bot{bot_token}/sendDocument"
    with open(file_path, 'rb') as f:
        files = {'document': f}
        data = {'chat_id': chat_id, 'caption': caption}
        requests.post(url, data=data, files=files)

def send_telegram_message(chat_id, text):
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    requests.post(url, json={'chat_id': chat_id, 'text': text})

def process_pdf():
    file_url = payload.get("file_url")
    file_name = payload.get("file_name", "document.pdf")
    chat_id = payload.get("chat_id")
    
    # 1. Unduh PDF dari server Telegram
    pdf_path = "temp.pdf"
    r = requests.get(file_url)
    with open(pdf_path, 'wb') as f:
        f.write(r.content)
        
    markdown_content = ""
    doc = fitz.open(pdf_path)
    
    # 2. Cek apakah PDF memiliki teks digital atau berupa gambar (scan)
    total_text_length = sum(len(page.get_text("text").strip()) for page in doc)
    
    if total_text_length > 100:
        # Jika teks digital tersedia, ekstrak langsung
        for page_num in range(len(doc)):
            page = doc[page_num]
            markdown_content += f"\n\n## Halaman {page_num + 1}\n\n"
            markdown_content += page.get_text("text")
    else:
        # Jika berupa gambar/scan, jalankan OCR (Tesseract)
        send_telegram_message(chat_id, "🔍 PDF terdeteksi berupa gambar/scan. Menjalankan mesin OCR cerdas di cloud...")
        images = convert_from_path(pdf_path)
        for page_num, image in enumerate(images):
            markdown_content += f"\n\n## Halaman {page_num + 1}\n\n"
            # Melakukan OCR membaca teks dalam gambar (Bahasa Indonesia & Inggris)
            text = pytesseract.image_to_string(image, lang='ind+eng')
            markdown_content += text

    md_path = "output.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(markdown_content)
        
    # 3. Kompilasi ke EPUB menggunakan Pandoc
    epub_name = file_name.replace(".pdf", ".epub")
    subprocess.run(["pandoc", md_path, "-o", epub_name, "--toc"])
    
    # 4. Kirim balik ke Telegram
    send_telegram_file(chat_id, epub_name, f"✨ Berhasil mengubah {file_name} menjadi EPUB bersih!")

def process_web():
    target_url = payload.get("target_url")
    chat_id = payload.get("chat_id")
    
    headers = {'User-Agent': 'Mozilla/5.0'}
    r = requests.get(target_url, headers=headers)
    soup = BeautifulSoup(r.text, 'html.parser')
    
    title = soup.title.string if soup.title else "Web Article"
    paragraphs = soup.find_all('p')
    body_text = f"# {title}\n\n*Sumber: {target_url}*\n\n"
    for p in paragraphs:
        body_text += p.get_text() + "\n\n"
        
    md_path = "web_output.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(body_text)
        
    epub_name = "artikel_web.epub"
    subprocess.run(["pandoc", md_path, "-o", epub_name, "--toc"])
    
    send_telegram_file(chat_id, epub_name, f"✨ Berhasil merakit web menjadi EPUB: {title}")

if __name__ == "__main__":
    try:
        if event_type == "convert_pdf":
            process_pdf()
        elif event_type == "convert_web":
            process_web()
    except Exception as e:
        chat_id = payload.get("chat_id")
        if chat_id and bot_token:
            send_telegram_message(chat_id, f"❌ Terjadi kesalahan di cloud: {str(e)}")
