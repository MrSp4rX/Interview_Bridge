from flask import Flask, render_template, request, redirect, url_for, jsonify, current_app, url_for, send_file
from flask import Flask, render_template, request, session
from flask_login import login_required, current_user
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from flask_login import LoginManager, login_user, login_required, logout_user, UserMixin, current_user
from werkzeug.utils import secure_filename
from flask_bcrypt import Bcrypt
from pymongo import MongoClient
from bson.objectid import ObjectId
from config import Config
from services.ai_engine import generate_feedback
import random
import os
import whisper
import json
from datetime import datetime, timedelta, timezone
from itsdangerous import URLSafeTimedSerializer
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import smtplib
from datetime import datetime, timedelta
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors
from reportlab.lib.units import inch
import io
from functools import wraps
from langchain_groq import ChatGroq
from langchain_core.output_parsers import JsonOutputParser
from pydantic import BaseModel, Field
from dotenv import load_dotenv

load_dotenv()

llm = ChatGroq(
    model="llama-3.1-8b-instant",
    temperature=0.2,
    max_tokens=800,
    max_retries=2
)


class QuizQuestion(BaseModel):
    question: str = Field(description="Question text")
    options: list[str] = Field(description="Four options")
    answer: str = Field(description="Correct option letter A/B/C/D")

class QuizSchema(BaseModel):
    questions: list[QuizQuestion]

parser = JsonOutputParser(pydantic_object=QuizSchema)

app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = "resumes"
app.config["SECRET_KEY"] = Config.SECRET_KEY
serializer = URLSafeTimedSerializer(app.config["SECRET_KEY"])
ALLOWED_EXTENSIONS = {"pdf"}
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

def calculate_profile_strength(profile):
    score = 0
    total = 100

    # Personal (20)
    personal = profile.get("personal", {})
    if all(personal.get(field) for field in ["phone", "city", "dob", "gender", "address"]):
        score += 20

    # Professional (20)
    professional = profile.get("professional", {})
    if all(professional.get(field) for field in ["preferred_role", "career_objective"]):
        score += 20

    # Skills (15)
    skills = profile.get("skills", {})
    if skills.get("technical") and skills.get("soft"):
        score += 15

    # Education (15)
    if profile.get("education"):
        score += 15

    # Projects (10)
    if profile.get("projects"):
        score += 10

    # Certifications (5)
    if profile.get("certifications"):
        score += 5

    # Resume (15)
    if profile.get("resume", {}).get("filename"):
        score += 15

    return score


def allowed_file(filename):
    return "." in filename and \
        filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

@app.context_processor
def inject_user_subscription():
    if current_user.is_authenticated:
        user = users_collection.find_one(
            {"_id": ObjectId(current_user.id)}
        )
        return {
            "subscription": user.get("subscription", "free")
        }
    return {
        "subscription": None
    }


@app.context_processor
def inject_user():
    if current_user.is_authenticated:
        user = users_collection.find_one(
            {"_id": ObjectId(current_user.id)}
        )
        return dict(user=user)
    return dict(user=None)

def premium_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = users_collection.find_one(
            {"_id": ObjectId(current_user.id)}
        )

        if not user or user.get("subscription") != "premium":
            return redirect("/usage")

        return f(*args, **kwargs)
    return decorated_function

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
@premium_required
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

    user = users_collection.find_one({"_id": ObjectId(current_user.id)})

    if not user:
        return redirect("/dashboard")

    if request.method == "POST":

        # ================= PERSONAL =================
        personal = {
            "phone": request.form.get("phone", "").strip(),
            "city": request.form.get("city", "").strip(),
            "dob": request.form.get("dob", "").strip(),
            "gender": request.form.get("gender", "").strip(),
            "address": request.form.get("address", "").strip(),
        }

        # ================= PROFESSIONAL =================
        professional = {
            "preferred_role": request.form.get("preferred_role", "").strip(),
            "experience_years": request.form.get("experience", "").strip(),
            "current_status": request.form.get("current_status", "").strip(),
            "career_objective": request.form.get("career_objective", "").strip(),
            "linkedin": request.form.get("linkedin", "").strip(),
            "github": request.form.get("github", "").strip(),
            "portfolio": request.form.get("portfolio", "").strip(),
        }

        # ================= SKILLS =================
        skills = {
            "technical": request.form.get("technical_skills", "").split(","),
            "soft": request.form.get("soft_skills", "").split(",")
        }

        # ================= EDUCATION =================
        education = []
        degrees = request.form.getlist("degree")
        colleges = request.form.getlist("college")
        years = request.form.getlist("year")
        cgpas = request.form.getlist("cgpa")

        for i in range(len(degrees)):
            if degrees[i] or colleges[i]:
                education.append({
                    "degree": degrees[i],
                    "college": colleges[i],
                    "year": years[i],
                    "cgpa": cgpas[i]
                })

        # ================= PROJECTS =================
        projects = []
        titles = request.form.getlist("project_title")
        descriptions = request.form.getlist("project_description")

        for i in range(len(titles)):
            if titles[i]:
                projects.append({
                    "title": titles[i],
                    "description": descriptions[i],
                    "tech_stack": [],
                    "github_link": ""
                })

        # ================= CERTIFICATIONS =================
        certifications = request.form.getlist("certification")

        # ================= RESUME =================
        resume_file = request.files.get("resume")
        resume_data = user.get("profile", {}).get("resume", {})

        if resume_file and resume_file.filename != "":
            if allowed_file(resume_file.filename):

                filename = secure_filename(f"{current_user.id}_resume.pdf")
                path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
                resume_file.save(path)

                resume_data = {
                    "filename": filename,
                    "uploaded_at": datetime.utcnow()
                }

        # ================= PROFILE OBJECT =================
        profile_data = {
            "personal": personal,
            "professional": professional,
            "skills": skills,
            "education": education,
            "projects": projects,
            "certifications": certifications,
            "achievements": request.form.getlist("achievement"),
            "resume": resume_data
        }

        # Calculate strength
        profile_data["profile_strength"] = calculate_profile_strength(profile_data)

        # ================= SAVE =================
        users_collection.update_one(
            {"_id": ObjectId(current_user.id)},
            {"$set": {"profile": profile_data}}
        )

        return redirect("/profile")

    profile_data = user.get("profile", {})
    profile_strength = profile_data.get("profile_strength", 0)

    return render_template(
        "profile.html",
        user=user,
        profile=profile_data,
        profile_strength=profile_strength
    )


@app.route("/download-resume")
@login_required
def download_resume():

    user = users_collection.find_one(
        {"_id": ObjectId(current_user.id)}
    )

    resume_filename = user.get("resume")

    if not resume_filename:
        return redirect("/profile")

    return send_file(
        os.path.join(app.config["UPLOAD_FOLDER"], resume_filename),
        as_attachment=True
    )



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
@premium_required
def improve_skill():
    user = users_collection.find_one(
        {"_id": ObjectId(current_user.id)}
    )
    questions = None
    score = None

    if request.method == "POST":
        if "language" in request.form:
            language = request.form.get("language")
            prompt = f"""
Generate 10 multiple choice questions for {language}.

Return ONLY valid JSON in this format:

{{
  "questions": [
    {{
      "question": "Question text",
      "options": ["Option A", "Option B", "Option C", "Option D"],
      "answer": "A"
    }}
  ]
}}

Rules:
- Return ONLY raw JSON
- No explanation
- No markdown
- No extra text
"""

            try:
                response = llm.invoke(prompt)
                response_text = response.content.strip()
                response_text = response_text.replace("```json", "")
                response_text = response_text.replace("```", "")
                response_text = response_text.strip()
                data = json.loads(response_text)

                questions = data.get("questions", [])

            except Exception as e:
                print("Groq LLM Error:", str(e))
                questions = []

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

    #  Use timezone aware datetime (fixes deprecation warning)
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

            #  Premium users get advanced evaluation
            advanced_mode = True if subscription == "premium" else False

            ai_response = generate_feedback(
                answer=answer,
                interview_type=interview_type,
                advanced=advanced_mode
            )

            # Safety fallback if AI fails
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

    scores = []

    for interview in interviews:
        confidence = interview.get("confidence")
        if isinstance(confidence, (int, float)):
            scores.append(confidence)

    avg_confidence = round(
        sum(scores) / len(scores), 2
    ) if scores else 0

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

@app.route("/final-interview", methods=["GET", "POST"])
@login_required
@premium_required
def final_interview():
    return render_template("final_interview.html")


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
@premium_required
def download_report():
    user = users_collection.find_one({"_id": ObjectId(current_user.id)})
    interviews = list(
        interviews_collection.find(
            {"user_id": current_user.id}
        ).sort("created_at", -1)
    )

    if not interviews:
        return "No interviews found."
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

@app.route("/cancel-subscription", methods=["POST", "GET"])
@login_required
def cancel_subscription():

    users_collection.update_one(
        {"_id": ObjectId(current_user.id)},
        {"$set": {"subscription": "free"}}
    )
    return redirect("/profile")

@app.route("/submit_answer", methods=["POST"])
@login_required
@premium_required
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


SYSTEM_PROMPT = """
You are a highly experienced HR interviewer with 15 years of experience.
You are strict, analytical, and emotionally intelligent.

Rules:
- Ask one question at a time.
- If the candidate avoids answering, press them politely but firmly.
- Analyze confidence, clarity, and depth.
- Ask follow-up questions based on their response.
- Maintain a professional but slightly intimidating tone.
- When the user types 'exit', give final evaluation.
- Final evaluation must include:
    - Score out of 10
    - Strengths
    - Weaknesses
    - Improvement suggestions
"""


# ---------------- Route ----------------
@app.route("/chat-interview", methods=["GET", "POST"])
@login_required
@premium_required
def chat_interview():
    interview_type = request.args.get("type", "hr")
    reset = request.args.get("reset", None)

    # ---------------- Handle Start Over ----------------
    if reset:
        session.pop("chat_history", None)
        return redirect(url_for("chat_interview", type=interview_type))

    # ---------------- Initialize session ----------------
    if "chat_history" not in session:
        session["chat_history"] = [{"role": "system", "content": SYSTEM_PROMPT}]

    raw_history = session["chat_history"]
    chat_history = []

    # ---------------- Convert session dicts to LangChain messages ----------------
    for msg in raw_history:
        if msg["role"] == "system":
            chat_history.append(SystemMessage(content=msg["content"]))
        elif msg["role"] == "human":
            chat_history.append(HumanMessage(content=msg["content"]))
        elif msg["role"] == "ai":
            chat_history.append(AIMessage(content=msg["content"]))

    # ---------------- Handle user POST message ----------------
    if request.method == "POST":
        user_text = request.form.get("user_message", "").strip()
        if user_text:
            if user_text.lower() == "exit":
                chat_history.append(HumanMessage(content="The candidate has ended the interview. Provide final evaluation."))
                response = llm.invoke(chat_history)
                chat_history.append(AIMessage(content=response.content))
            else:
                chat_history.append(HumanMessage(content=user_text))
                response = llm.invoke(chat_history)
                chat_history.append(AIMessage(content=response.content))

            # Save back as JSON-serializable dicts
            session["chat_history"] = [
                {"role": "system" if isinstance(m, SystemMessage) else "human" if isinstance(m, HumanMessage) else "ai",
                 "content": m.content}
                for m in chat_history
            ]

    # ---------------- Prepare for frontend display ----------------
    display_history = [
        {"role": "HR-Donald" if isinstance(m, AIMessage) else "You", "content": m.content}
        for m in chat_history if not isinstance(m, SystemMessage)
    ]

    return render_template(
        "chat_interview.html",
        chat_history=display_history,
        interview_type=interview_type
    )


# ------------------- Voice Interview Page -------------------
@app.route("/voice-interview")
@login_required
@premium_required
def voice_interview():
    # Initialize session chat history if not exists
    if "voice_chat_history" not in session:
        session["voice_chat_history"] = [
            {"role": "system", "content": SYSTEM_PROMPT}
        ]
    return render_template("voice_interview.html")


# ------------------- AI Response Endpoint -------------------
@app.route("/voice-interview", methods=["POST"])
@login_required
@premium_required
def voice_interview_post():
    user_text = request.json.get("user_text", "").strip()
    if not user_text:
        return jsonify({"ai_reply": "Please say something first."})

    # Load chat history from session
    raw_history = session.get("voice_chat_history", [])
    chat_history = []

    for msg in raw_history:
        if msg["role"] == "system":
            chat_history.append(SystemMessage(content=msg["content"]))
        elif msg["role"] == "human":
            chat_history.append(HumanMessage(content=msg["content"]))
        elif msg["role"] == "ai":
            chat_history.append(AIMessage(content=msg["content"]))

    # Handle exit
    if user_text.lower() == "exit":
        chat_history.append(HumanMessage(content="The candidate has ended the interview. Provide final evaluation."))
        response = llm.invoke(chat_history)
        chat_history.append(AIMessage(content=response.content))

        # Clear session after final evaluation
        session.pop("voice_chat_history", None)
        return jsonify({"ai_reply": response.content})

    # Normal flow
    chat_history.append(HumanMessage(content=user_text))
    response = llm.invoke(chat_history)
    chat_history.append(AIMessage(content=response.content))

    # Save updated history back to session (JSON serializable)
    session["voice_chat_history"] = [
        {"role": "system" if isinstance(m, SystemMessage)
                 else "human" if isinstance(m, HumanMessage)
                 else "ai",
         "content": m.content}
        for m in chat_history
    ]

    return jsonify({"ai_reply": response.content})


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
