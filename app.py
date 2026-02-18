from flask import Flask, render_template, request, redirect, url_for, jsonify, current_app, url_for, send_file
from flask_login import LoginManager, login_user, login_required, logout_user, UserMixin, current_user
from flask_bcrypt import Bcrypt
from pymongo import MongoClient
from bson.objectid import ObjectId
from config import Config
from services.ai_engine import generate_feedback, extract_json
import random
import os
import whisper
from datetime import datetime, timedelta, timezone
from itsdangerous import URLSafeTimedSerializer
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import smtplib
from datetime import datetime, timedelta
from services.pdf_generator import generate_pdf_report
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib import colors
from reportlab.lib.units import inch
import io


app = Flask(__name__)
app.config["SECRET_KEY"] = Config.SECRET_KEY
serializer = URLSafeTimedSerializer(app.config["SECRET_KEY"])
app.config.from_object(Config)

bcrypt = Bcrypt(app)

# MongoDB
client = MongoClient(app.config["MONGO_URI"])
db = client[app.config["DB_NAME"]]

users_collection = db["users"]
interviews_collection = db["interviews"]

login_manager = LoginManager(app)
login_manager.login_view = "login"
model = whisper.load_model("tiny", device="cpu")
QUESTIONS = [
    "Tell me about yourself",
    "Why should we hire you?",
    "Describe a challenge you faced",
    "Explain your final year project"
]

def generate_reset_token(email):
    serializer = URLSafeTimedSerializer(app.config["SECRET_KEY"])
    return serializer.dumps(
        email,
        salt=app.config["SECURITY_PASSWORD_SALT"]
    )


def confirm_reset_token(token, expiration=1800):  # 30 minutes
    serializer = URLSafeTimedSerializer(app.config["SECRET_KEY"])
    try:
        email = serializer.loads(
            token,
            salt=app.config["SECURITY_PASSWORD_SALT"],
            max_age=expiration
        )
    except Exception:
        return None
    return email


def send_reset_email(email, token):

    reset_url = url_for("reset_password", token=token, _external=True)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Reset Your Password - Interview Bridge"
    msg["From"] = current_app.config["MAIL_DEFAULT_SENDER"]
    msg["To"] = email

    # Plain Text Version (fallback)
    text_content = f"""
Hello,

You requested a password reset.

Click the link below to reset your password:
{reset_url}

This link will expire in 30 minutes.

If you did not request this, please ignore this email.

— Interview Bridge Team
"""

    # Professional HTML Email
    html_content = f"""
    <html>
    <body style="font-family: Arial, sans-serif; background-color:#f4f6f9; padding:20px;">
        <div style="max-width:600px; margin:auto; background:white; padding:30px; border-radius:8px;">
            
            <h2 style="color:#4e73df; text-align:center;">
                🎤 Interview Bridge
            </h2>

            <p>Hello,</p>

            <p>You recently requested to reset your password.</p>

            <div style="text-align:center; margin:30px 0;">
                <a href="{reset_url}"
                   style="background-color:#4e73df;
                          color:white;
                          padding:12px 24px;
                          text-decoration:none;
                          border-radius:6px;
                          font-weight:bold;">
                    Reset Password
                </a>
            </div>

            <p style="font-size:14px; color:#555;">
                This link will expire in 30 minutes.
            </p>

            <p style="font-size:14px; color:#555;">
                If you didn’t request this, you can safely ignore this email.
            </p>

            <hr style="margin-top:30px;">

            <p style="font-size:12px; color:#999; text-align:center;">
                © 2026 Interview Bridge. All rights reserved.
            </p>

        </div>
    </body>
    </html>
    """

    msg.attach(MIMEText(text_content, "plain"))
    msg.attach(MIMEText(html_content, "html"))

    # Send email using config
    server = smtplib.SMTP(
        current_app.config["MAIL_SERVER"],
        current_app.config["MAIL_PORT"]
    )

    if current_app.config["MAIL_USE_TLS"]:
        server.starttls()

    server.login(
        current_app.config["MAIL_USERNAME"],
        current_app.config["MAIL_PASSWORD"]
    )

    server.sendmail(
        current_app.config["MAIL_USERNAME"],
        email,
        msg.as_string()
    )

    server.quit()



class User(UserMixin):
    def __init__(self, user_data):
        self.id = str(user_data["_id"])
        self.name = user_data["name"]
        self.email = user_data["email"]

@login_manager.user_loader
def load_user(user_id):
    user = users_collection.find_one({"_id": ObjectId(user_id)})
    if user:
        return User(user)
    return None

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():

    if request.method == "POST":

        email = request.form.get("email")
        user = users_collection.find_one({"email": email})

        if user:
            token = generate_reset_token(email)
            send_reset_email(email, token)

        return render_template("forgot_password_sent.html")

    return render_template("forgot_password.html")


@app.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):

    email = confirm_reset_token(token)

    if not email:
        return "The reset link is invalid or has expired."

    if request.method == "POST":

        new_password = request.form.get("password")
        hashed_pw = bcrypt.generate_password_hash(new_password).decode("utf-8")

        users_collection.update_one(
            {"email": email},
            {"$set": {"password": hashed_pw}}
        )

        return redirect("/login")

    return render_template("reset_password.html")


@app.route("/transcribe", methods=["POST"])
@login_required
def transcribe_audio():

    if "audio" not in request.files:
        return jsonify({"error": "No audio file"}), 400

    audio_file = request.files["audio"]
    file_path = "temp_audio.webm"
    audio_file.save(file_path)

    try:
        result = model.transcribe(file_path)
        text = result["text"]

        return jsonify({"text": text})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

    finally:
        if os.path.exists(file_path):
            os.remove(file_path)


@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():

    user = users_collection.find_one(
        {"_id": ObjectId(current_user.id)}
    )

    if not user:
        return redirect("/dashboard")

    if request.method == "POST":

        # ================= EDUCATION =================
        education = []
        degrees = request.form.getlist("degree")
        colleges = request.form.getlist("college")
        years = request.form.getlist("year")
        cgpas = request.form.getlist("cgpa")

        for i in range(len(degrees)):
            # Skip completely empty rows
            if not degrees[i] and not colleges[i]:
                continue

            education.append({
                "degree": degrees[i],
                "college": colleges[i],
                "year": years[i],
                "cgpa": cgpas[i]
            })

        # ================= OTHER MULTI FIELDS =================
        certifications = [
            c for c in request.form.getlist("certification") if c.strip()
        ]

        projects = [
            p for p in request.form.getlist("project") if p.strip()
        ]

        achievements = [
            a for a in request.form.getlist("achievement") if a.strip()
        ]

        # ================= UPDATE DATABASE =================
        users_collection.update_one(
            {"_id": ObjectId(current_user.id)},
            {"$set": {
                "phone": request.form.get("phone", "").strip(),
                "city": request.form.get("city", "").strip(),
                "career_objective": request.form.get("career_objective", "").strip(),
                "technical_skills": request.form.get("technical_skills", "").strip(),
                "soft_skills": request.form.get("soft_skills", "").strip(),
                "education": education,
                "certifications": certifications,
                "projects": projects,
                "achievements": achievements
            }}
        )

        return redirect("/profile")

    return render_template("profile.html", user=user)


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        hashed_pw = bcrypt.generate_password_hash(
            request.form["password"]
        ).decode("utf-8")

        users_collection.insert_one({
            "name": request.form["name"],
            "email": request.form["email"],
            "password": hashed_pw,
            "subscription": "free"
        })

        return redirect("/login")

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = users_collection.find_one({"email": request.form["email"]})

        if user and bcrypt.check_password_hash(
            user["password"], request.form["password"]
        ):
            login_user(User(user))
            return redirect("/dashboard")

    return render_template("login.html")

HR_QUESTIONS = [
    "Tell me about yourself.",
    "Why should we hire you?",
    "What are your strengths and weaknesses?",
    "Describe a time you handled pressure.",
    "Where do you see yourself in 5 years?",
    "Describe a conflict in a team and how you handled it.",
    "Why do you want to join our company?",
    "Tell me about a failure and what you learned from it.",
    "How do you handle criticism?",
    "Describe your leadership experience."
]

TECH_QUESTIONS = [
    "Explain REST API architecture.",
    "What is normalization in databases?",
    "Difference between SQL and NoSQL?",
    "Explain OOP principles with examples.",
    "What is indexing in databases?",
    "Explain the difference between GET and POST.",
    "What is multithreading?",
    "Explain time complexity with example.",
    "What is dependency injection?",
    "How does authentication work in web apps?"
]

@app.route("/improve-skill", methods=["GET", "POST"])
@login_required
def improve_skill():

    user = users_collection.find_one(
        {"_id": ObjectId(current_user.id)}
    )

    # 🔒 Only premium users allowed
    if user.get("subscription") != "premium":
        return redirect("/upgrade")

    questions = None
    score = None

    if request.method == "POST":

        # ================= Generate Quiz =================
        if "language" in request.form:

            language = request.form.get("language")

            prompt = f"""
Generate 10 multiple choice questions for {language}.
Return ONLY valid JSON in this format:

{{
  "questions": [
    {{
      "question": "text",
      "options": ["Option A", "Option B", "Option C", "Option D"],
      "answer": "B"
    }}
  ]
}}
"""

            import requests

            response = requests.post(
                "http://localhost:11434/api/generate",
                json={
                    "model": "llama3",
                    "prompt": prompt,
                    "stream": False
                }
            )

            raw_text = response.json().get("response", "")
            print("RAW LLM TEXT:", raw_text)

            quiz_data = extract_json(raw_text)

            if quiz_data:
                questions = quiz_data.get("questions", [])

        # ================= Submit Quiz =================
        elif "submit_quiz" in request.form:

            total = int(request.form.get("total_questions", 0))
            correct = 0

            for i in range(total):
                user_answer = request.form.get(f"user_answer_{i}")
                correct_answer = request.form.get(f"correct_answer_{i}")

                if user_answer and correct_answer and user_answer == correct_answer:
                    correct += 1

            score = round((correct / total) * 100, 2) if total > 0 else 0

    return render_template(
        "improve_skill.html",
        questions=questions,
        score=score
    )





@app.route("/dashboard", methods=["GET", "POST"])
@login_required
def dashboard():

    user_data = users_collection.find_one(
        {"_id": ObjectId(current_user.id)}
    )

    subscription = user_data.get("subscription", "free")

    interview_type = request.args.get("type", "hr")
    question_pool = TECH_QUESTIONS if interview_type == "technical" else HR_QUESTIONS
    question = random.choice(question_pool)

    feedback = None
    limit_reached = False

    # ✅ Use timezone aware datetime (fixes deprecation warning)
    one_week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    FREE_LIMIT = 20

    weekly_sessions = interviews_collection.count_documents({
        "user_id": current_user.id,
        "created_at": {"$gte": one_week_ago}
    })

    # ================= POST =================
    if request.method == "POST":

        weekly_sessions = interviews_collection.count_documents({
            "user_id": current_user.id,
            "created_at": {"$gte": one_week_ago}
        })

        if subscription == "free" and weekly_sessions >= FREE_LIMIT:
            limit_reached = True
        else:
            question = request.form["question"]
            answer = request.form["answer"]
            interview_type = request.form.get("interview_type", "hr")

            # ✅ Premium users get advanced evaluation
            advanced_mode = True if subscription == "premium" else False

            ai_response = generate_feedback(
                answer=answer,
                interview_type=interview_type,
                advanced=advanced_mode
            )

            # ✅ Safety fallback if AI fails
            if not ai_response or not isinstance(ai_response, dict):
                ai_response = {}

            # ================= SAFE EXTRACTION =================
            grammar_score = ai_response.get("grammar_score", 5)
            confidence_score = ai_response.get("confidence_score", 5)
            improved_answer = ai_response.get(
                "improved_answer",
                "Could not generate improved answer."
            )

            # Only for premium + technical
            technical_score = None
            if subscription == "premium" and interview_type == "technical":
                technical_score = ai_response.get("technical_depth_score", 5)

            # Optional advanced fields
            clarity_score = ai_response.get("clarity_score")
            overall_score = ai_response.get("overall_score")
            strengths = ai_response.get("strengths")
            weaknesses = ai_response.get("weaknesses")
            suggestions = ai_response.get("suggestions")

            feedback = {
                "grammar_score": grammar_score,
                "confidence_score": confidence_score,
                "technical_score": technical_score,
                "clarity_score": clarity_score,
                "overall_score": overall_score,
                "strengths": strengths,
                "weaknesses": weaknesses,
                "suggestions": suggestions,
                "improved_answer": improved_answer
            }

            interviews_collection.insert_one({
                "user_id": current_user.id,
                "question": question,
                "answer": answer,
                "interview_type": interview_type,
                "feedback": feedback,
                "created_at": datetime.now(timezone.utc)
            })

            weekly_sessions += 1

    # ================= FETCH HISTORY =================
    interviews = list(
        interviews_collection.find(
            {"user_id": current_user.id}
        ).sort("created_at", -1)
    )

    recent_interviews = interviews[:3]

    scores = [
        item.get("feedback", {}).get("confidence_score", 0)
        for item in interviews
    ]

    avg_confidence = sum(scores) / len(scores) if scores else 0
    readiness = round((avg_confidence / 10) * 100, 1)

    return render_template(
        "dashboard.html",
        user=user_data,
        feedback=feedback,
        scores=scores,
        question=question,
        readiness=readiness,
        interview_type=interview_type,
        weekly_sessions=weekly_sessions,
        free_limit=FREE_LIMIT,
        limit_reached=limit_reached,
        recent_interviews=recent_interviews,
        subscription=subscription
    )




@app.route("/history")
@login_required
def history():

    interviews = list(
        interviews_collection.find(
            {"user_id": current_user.id}
        ).sort("created_at", -1)
    )

    return render_template(
        "history.html",
        interviews=interviews
    )

@app.route("/download-report")
@login_required
def download_report():

    user = users_collection.find_one({"_id": ObjectId(current_user.id)})

    # 🔒 Allow only premium users
    if user.get("subscription") != "premium":
        return redirect("/usage")

    interviews = list(
        interviews_collection.find(
            {"user_id": current_user.id}
        ).sort("created_at", -1)
    )

    if not interviews:
        return "No interviews found."

    # Create PDF in memory
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    elements = []

    styles = getSampleStyleSheet()
    title_style = styles["Heading1"]
    normal_style = styles["Normal"]

    elements.append(Paragraph("Interview Performance Report", title_style))
    elements.append(Spacer(1, 0.3 * inch))

    for interview in interviews[:10]:  # last 10 sessions

        elements.append(Paragraph(
            f"<b>Date:</b> {interview['created_at'].strftime('%d %b %Y')}",
            normal_style
        ))
        elements.append(Spacer(1, 0.1 * inch))

        elements.append(Paragraph(
            f"<b>Question:</b> {interview['question']}",
            normal_style
        ))
        elements.append(Spacer(1, 0.1 * inch))

        elements.append(Paragraph(
            f"<b>Confidence Score:</b> {interview['feedback']['confidence_score']}/10",
            normal_style
        ))
        elements.append(Spacer(1, 0.2 * inch))

    doc.build(elements)

    buffer.seek(0)

    return send_file(
        buffer,
        as_attachment=True,
        download_name="Interview_Report.pdf",
        mimetype="application/pdf"
    )

@app.route("/cancel-subscription", methods=["POST"])
@login_required
def cancel_subscription():

    users_collection.update_one(
        {"_id": ObjectId(current_user.id)},
        {"$set": {"subscription": "free"}}
    )

    return redirect("/profile")




@app.route("/interview")
@login_required
def interview():
    question = random.choice(QUESTIONS)
    return render_template("interview.html", question=question)

@app.route("/submit_answer", methods=["POST"])
@login_required
def submit_answer():
    answer = request.form["answer"]
    question = request.form["question"]

    ai_response = generate_feedback(answer)

    corrected = ai_response.get("corrected_version")
    feedback = ai_response.get("feedback")
    fluency_score = ai_response.get("fluency_score", 0)

    score = min(fluency_score * 10, 100)

    interviews_collection.insert_one({
        "user_id": current_user.id,
        "question": question,
        "answer": answer,
        "corrected": corrected,
        "feedback": feedback,
        "score": score
    })

    return render_template(
        "result.html",
        corrected=corrected,
        feedback=feedback,
        score=score
    )


@app.route("/usage")
@login_required
def usage():

    user_data = users_collection.find_one(
        {"_id": ObjectId(current_user.id)}
    )

    one_week_ago = datetime.utcnow() - timedelta(days=7)

    weekly_sessions = interviews_collection.count_documents({
        "user_id": current_user.id,
        "created_at": {"$gte": one_week_ago}
    })

    FREE_LIMIT = 20

    remaining = max(FREE_LIMIT - weekly_sessions, 0)

    progress_percent = min((weekly_sessions / FREE_LIMIT) * 100, 100)

    return render_template(
        "usage.html",
        weekly_sessions=weekly_sessions,
        free_limit=FREE_LIMIT,
        remaining=remaining,
        progress_percent=progress_percent,
        subscription=user_data.get("subscription", "free")
    )



@app.route("/upgrade")
@login_required
def upgrade():

    users_collection.update_one(
        {"_id": ObjectId(current_user.id)},
        {"$set": {"subscription": "premium"}}
    )

    return redirect("/usage")


@app.route("/logout")
def logout():
    logout_user()
    return redirect("/")

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0")
