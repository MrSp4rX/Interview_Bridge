from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
import io

def generate_pdf_report(user, interviews):
    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter
    y = height - 40
    p.setFont("Helvetica-Bold", 16)
    p.drawString(50, y, "Interview Performance Report")
    y -= 30
    p.setFont("Helvetica", 12)
    p.drawString(50, y, f"User: {user['name']}")
    y -= 20
    p.drawString(50, y, f"Email: {user['email']}")
    y -= 30

    for interview in interviews[:10]:
        p.drawString(50, y, f"Q: {interview['question']}")
        y -= 15
        p.drawString(50, y, f"Confidence: {interview['feedback'].get('confidence_score',0)}/10")
        y -= 25
        if y < 100:
            p.showPage()
            y = height - 40

    p.save()
    buffer.seek(0)
    return buffer
