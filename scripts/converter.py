import os
import json
import subprocess
import requests
import fitz  # PyMuPDF
from bs4 import BeautifulSoup
import pytesseract
from pdf2image import convert_from_path
import re

# Mengambil variabel dari lingkungan GitHub Actions
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

def clean_and_format_text(text):
    """
    Fungsi cerdas universal untuk mendeteksi judul/bab dengan berbagai format,
    memisahnya dari paragraf, serta memberikan format Heading dan Bold (**teks**).
    """
    lines = text.split('\n')
    formatted_lines = []
    
    for line in lines:
        cleaned_line = line.strip()
        if not cleaned_line:
            continue
            
        # 1. Filter sampah OCR dari gambar (simbol aneh & terlalu pendek)
        if len(cleaned_line) < 3 and not cleaned_line.isalnum():
            continue
            
        # 2. Logika Deteksi Judul/Bab Universal
        is_heading = False
        
        # Kriteria: Panjang baris relatif pendek (< 70 karakter) dan TIDAK diakhiri tanda baca kalimat
        is_short_line = len(cleaned_line) < 70 and not cleaned_line.endswith(('.', '?', '!', ',', ';'))
        
        if is_short_line:
            # Pola 1: Awalan penomoran bab/bagian (Bab 1, Chapter II, Bagian 3, 1. Pendahuluan, dll)
            if re.match(r'^(bab\s+[ivxlc0-9]+|chapter\s+[0-9]+|bagian\s+[0-9]+|pendahuluan|penutup|kesimpulan|lampiran|epilog|prolog|[0-9]+(\.[0-9]+)*\s+[A-Z])', cleaned_line, re.IGNORECASE):
                is_heading = True
                
            # Pola 2: Huruf kapital seluruhnya (biasanya judul bab atau sub-bab utama)
            elif cleaned_line.isupper() and len(cleaned_line) > 3:
                is_heading = True
                
            # Pola 3: Format Title Case pendek tanpa titik (Setiap Kata Diawali Huruf Besar)
            elif cleaned_line.istitle() and len(cleaned_line.split()) < 8:
                is_heading = True

        # Terapkan hasil format Markdown (Heading + Bold agar terpisah rapi dari paragraf)
        if is_heading:
            formatted_lines.append(f"\n\n## **{cleaned_line}**\n\n")
        else:
            formatted_lines.append(cleaned_line + " ")
            
    return "".join(formatted_lines)

def process_pdf():
    file_url = payload.get("file_url")
    file_name = payload.get("file_name", "document.pdf")
    chat_id = payload.get("chat_id")
    
    pdf_path = "temp.pdf"
    r = requests.get(file_url)
    with open(pdf_path, 'wb') as f:
        f.write(r.content)
        
    doc = fitz.open(pdf_path)
    markdown_content = ""
    os.makedirs("extracted_images", exist_ok=True)
    
    cover_image_path = None

    # 1. Ambil halaman pertama sebagai Cover Buku secara otomatis
    if len(doc) > 0:
        first_page = doc[0]
        pix = first_page.get_pixmap(dpi=150)
        cover_image_path = "extracted_images/cover.jpg"
        pix.save(cover_image_path)

    total_text_length = sum(len(page.get_text("text").strip()) for page in doc)
    
    if total_text_length > 100:
        # Jika PDF digital, ekstrak teks dan gambar per halaman
        for page_num in range(len(doc)):
            page = doc[page_num]
            raw_text = page.get_text('text')
            markdown_content += clean_and_format_text(raw_text)
            
            # Ekstrak gambar di halaman tersebut
            image_list = page.get_images(full=True)
            for img_index, img in enumerate(image_list):
                xref = img[0]
                base_image = doc.extract_image(xref)
                image_bytes = base_image["image"]
                image_ext = base_image["ext"]
                image_filename = f"extracted_images/p{page_num+1}_img{img_index}.{image_ext}"
                with open(image_filename, "wb") as img_file:
                    img_file.write(image_bytes)
                markdown_content += f"\n\n![Gambar]({image_filename})\n\n"
    else:
        # Jika PDF scan, jalankan OCR dengan pembersihan teks
        send_telegram_message(chat_id, "🔍 PDF berupa scan/gambar. Menjalankan mesin OCR cerdas & pembersihan teks...")
        images = convert_from_path(pdf_path)
        for page_num, image in enumerate(images):
            text = pytesseract.image_to_string(image, lang='ind+eng')
            markdown_content += clean_and_format_text(text)

    md_path = "output.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(markdown_content)
        
    # 2. Kompilasi ke EPUB menggunakan Pandoc (Menyertakan cover jika ada)
    epub_name = file_name.replace(".pdf", ".epub")
    pandoc_command = ["pandoc", md_path, "-o", epub_name, "--toc"]
    
    if cover_image_path and os.path.exists(cover_image_path):
        pandoc_command.extend([f"--epub-cover-image={cover_image_path}"])

    subprocess.run(pandoc_command)
    
    # 3. Kirim balik ke Telegram
    send_telegram_file(chat_id, epub_name, f"✨ Berhasil mengubah {file_name} menjadi EPUB (Cover, Gambar, & Bab Bold Rapi)!")

def process_web():
    target_url = payload.get("target_url")
    chat_id = payload.get("chat_id")
    
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    
    try:
        # Mengatasi error SSL kedaluwarsa (seperti pada link kask.us)
        r = requests.get(target_url, headers=headers, verify=False, timeout=15)
        r.raise_for_status()
    except Exception as e:
        send_telegram_message(chat_id, f"❌ Gagal mengakses web. Error SSL/Koneksi: {str(e)}")
        return

    soup = BeautifulSoup(r.text, 'html.parser')
    title = soup.title.string if soup.title else "Web Article"
    
    paragraphs = soup.find_all(['p', 'article', 'div'])
    body_text = f"# **{title}**\n\n*Sumber: {target_url}*\n\n"
    
    for p in paragraphs:
        text = p.get_text().strip()
        if len(text) > 40:
            body_text += text + "\n\n"
        
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
