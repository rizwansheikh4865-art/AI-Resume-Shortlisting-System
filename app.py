import os
import re
import sqlite3
from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from PyPDF2 import PdfReader
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from pdf2image import convert_from_path
import pytesseract

app = Flask(__name__)
app.secret_key = "aihigh_secret_key_2025"

UPLOAD_FOLDER = "uploads"
ALLOWED_EXTENSIONS = {"pdf"}
DATABASE = "aihigh.db"

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

SKILL_KEYWORDS = [
    "python", "java", "c", "c++", "javascript", "html", "css", "flask", "django",
    "sql", "mysql", "mongodb", "machine learning", "deep learning", "nlp",
    "data analysis", "pandas", "numpy", "power bi", "excel", "communication",
    "teamwork", "leadership", "problem solving", "git", "github", "react",
    "node.js", "api", "aws", "docker"
]


def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db_connection()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            username TEXT NOT NULL UNIQUE,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS contact_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            message TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    admin_user = conn.execute(
        "SELECT * FROM users WHERE username = ?",
        ("admin",)
    ).fetchone()

    if not admin_user:
        conn.execute("""
            INSERT INTO users (full_name, username, email, password_hash, role)
            VALUES (?, ?, ?, ?, ?)
        """, (
            "Administrator",
            "admin",
            "admin@aihigh.com",
            generate_password_hash("1234"),
            "admin"
        ))

    conn.commit()
    conn.close()


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def extract_text_with_ocr(pdf_path):
    ocr_text = ""

    try:
        images = convert_from_path(pdf_path)
        for image in images:
            text = pytesseract.image_to_string(image)
            if text:
                ocr_text += text + "\n"
    except Exception as error:
        print(f"OCR extraction error: {error}")

    return ocr_text.strip()


def extract_text_from_pdf(pdf_path):
    extracted_text = ""

    try:
        reader = PdfReader(pdf_path)
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                extracted_text += page_text + "\n"
    except Exception as error:
        print(f"PDF text extraction error: {error}")

    if len(extracted_text.strip()) < 50:
        ocr_text = extract_text_with_ocr(pdf_path)
        if ocr_text.strip():
            extracted_text += "\n" + ocr_text

    return extracted_text.strip()


def clean_text(text):
    text = text.lower()
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def extract_skills(text):
    text = clean_text(text)
    found_skills = []

    for skill in SKILL_KEYWORDS:
        if skill.lower() in text:
            found_skills.append(skill)

    return sorted(list(set(found_skills)))


def get_missing_skills(job_description, resume_text):
    jd_skills = extract_skills(job_description)
    resume_skills = extract_skills(resume_text)

    missing = [skill for skill in jd_skills if skill not in resume_skills]
    return jd_skills, resume_skills, missing


def generate_suggestions(missing_skills):
    suggestions = []

    if not missing_skills:
        suggestions.append("Excellent match. Resume covers all major required skills.")
        return suggestions

    for skill in missing_skills:
        suggestions.append(f"Consider adding or improving evidence of '{skill}' in the resume.")

    return suggestions


def rank_resumes(job_description, resumes_data):
    documents = [job_description] + [resume["text"] for resume in resumes_data]

    vectorizer = TfidfVectorizer(stop_words="english")
    tfidf_matrix = vectorizer.fit_transform(documents)

    job_vector = tfidf_matrix[0:1]
    resume_vectors = tfidf_matrix[1:]
    similarity_scores = cosine_similarity(job_vector, resume_vectors).flatten()

    ranked_results = []

    for index, resume in enumerate(resumes_data):
        score = round(similarity_scores[index] * 100, 2)

        _, found_skills, missing_skills = get_missing_skills(
            job_description,
            resume["text"]
        )

        ranked_results.append({
            "filename": resume["filename"],
            "score": score,
            "found_skills": found_skills,
            "missing_skills": missing_skills,
            "suggestions": generate_suggestions(missing_skills),
            "text_preview": resume["text"][:500] + "..." if len(resume["text"]) > 500 else resume["text"]
        })

    ranked_results.sort(key=lambda x: x["score"], reverse=True)
    return ranked_results


def is_logged_in():
    return session.get("logged_in", False)


@app.route("/")
def home():
    return render_template("home.html")


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/contact", methods=["GET", "POST"])
def contact():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip()
        message = request.form.get("message", "").strip()

        if not name or not email or not message:
            flash("Please fill in all contact form fields.", "danger")
            return redirect(url_for("contact"))

        conn = get_db_connection()
        conn.execute(
            "INSERT INTO contact_messages (name, email, message) VALUES (?, ?, ?)",
            (name, email, message)
        )
        conn.commit()
        conn.close()

        flash("Your message has been sent successfully.", "success")
        return redirect(url_for("contact"))

    return render_template("contact.html")


@app.route("/credits")
def credits():
    return render_template("credits.html")


@app.route("/terms")
def terms():
    return render_template("terms.html")


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        username = request.form.get("username", "").strip().lower()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "").strip()
        confirm_password = request.form.get("confirm_password", "").strip()

        if not full_name or not username or not email or not password or not confirm_password:
            flash("Please fill in all signup fields.", "danger")
            return redirect(url_for("signup"))

        if password != confirm_password:
            flash("Passwords do not match.", "danger")
            return redirect(url_for("signup"))

        if len(password) < 4:
            flash("Password must be at least 4 characters long.", "danger")
            return redirect(url_for("signup"))

        conn = get_db_connection()

        existing_user = conn.execute(
            "SELECT * FROM users WHERE username = ? OR email = ?",
            (username, email)
        ).fetchone()

        if existing_user:
            conn.close()
            flash("Username or email already exists.", "warning")
            return redirect(url_for("signup"))

        password_hash = generate_password_hash(password)

        conn.execute("""
            INSERT INTO users (full_name, username, email, password_hash, role)
            VALUES (?, ?, ?, ?, ?)
        """, (full_name, username, email, password_hash, "user"))

        conn.commit()
        conn.close()

        flash("Account created successfully. Please login.", "success")
        return redirect(url_for("login"))

    return render_template("signup.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        identifier = request.form.get("identifier", "").strip().lower()
        password = request.form.get("password", "").strip()

        if not identifier or not password:
            flash("Please enter your login details.", "danger")
            return redirect(url_for("login"))

        conn = get_db_connection()
        user = conn.execute(
            "SELECT * FROM users WHERE username = ? OR email = ?",
            (identifier, identifier)
        ).fetchone()
        conn.close()

        if user and check_password_hash(user["password_hash"], password):
            session["logged_in"] = True
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["full_name"] = user["full_name"]
            session["role"] = user["role"]

            flash("Login successful!", "success")
            return redirect(url_for("upload_resume"))

        flash("Invalid username/email or password.", "danger")
        return redirect(url_for("login"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("home"))


@app.route("/upload", methods=["GET", "POST"])
def upload_resume():
    if not is_logged_in():
        flash("Please login first to access the dashboard.", "warning")
        return redirect(url_for("login"))

    if request.method == "POST":
        job_description = request.form.get("job_description", "").strip()
        resume_files = request.files.getlist("resumes")

        if not job_description:
            flash("Please enter a job description.", "danger")
            return redirect(url_for("upload_resume"))

        if not resume_files or resume_files[0].filename == "":
            flash("Please upload at least one PDF resume.", "danger")
            return redirect(url_for("upload_resume"))

        resumes_data = []

        for file in resume_files:
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
                file.save(filepath)

                extracted_text = extract_text_from_pdf(filepath)

                if extracted_text.strip():
                    resumes_data.append({
                        "filename": filename,
                        "text": clean_text(extracted_text)
                    })

        if not resumes_data:
            flash("No readable resumes found. Please upload valid PDF files.", "danger")
            return redirect(url_for("upload_resume"))

        ranked_results = rank_resumes(clean_text(job_description), resumes_data)
        top_candidate = ranked_results[0] if ranked_results else None

        return render_template(
            "result.html",
            ranked_results=ranked_results,
            top_candidate=top_candidate,
            total_resumes=len(ranked_results),
            job_description=job_description
        )

    return render_template("upload.html")


if __name__ == "__main__":
    init_db()
    app.run(debug=True)
