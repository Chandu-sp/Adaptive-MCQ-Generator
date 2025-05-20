
import streamlit as st
import sqlite3
import bcrypt
import google.generativeai as genai
import json
import uuid
from fpdf import FPDF
from gtts import gTTS
#from docx import Document
from PyPDF2 import PdfReader
import PyPDF2
import os
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import plotly.express as px




# Configure Gemini API key
genai.configure(api_key="AIzaSyAkmsXJIMknAkMHstTNSTI8xAXBTBe5HGs")

# SQLite Database Setup
conn = sqlite3.connect("users.db", check_same_thread=False)
c = conn.cursor()


# Create necessary tables if they don't exist
c.execute('''CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE,
    password TEXT,
    role TEXT
)''')

c.execute('''CREATE TABLE IF NOT EXISTS quizzes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    teacher TEXT,
    title TEXT,
    mcqs TEXT,
    answers TEXT
)''')

c.execute('''CREATE TABLE IF NOT EXISTS lectures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    teacher TEXT,
    title TEXT,
    content TEXT
)''')

c.execute('''CREATE TABLE IF NOT EXISTS scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student TEXT,
    quiz_id INTEGER,
    student_answers TEXT,
    score INTEGER DEFAULT NULL,
    evaluated_by TEXT DEFAULT NULL,
    status TEXT DEFAULT 'Pending'
)''')

c.execute('''CREATE TABLE IF NOT EXISTS quiz_titles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT UNIQUE
)''')

c.execute('''CREATE TABLE IF NOT EXISTS marks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER,
    quiz_title TEXT,
    subject TEXT,
    teacher_name TEXT,
    score INTEGER,
    status TEXT DEFAULT 'Pending'
)''')


def ensure_status_column():
    try:
        c.execute("ALTER TABLE scores ADD COLUMN status TEXT DEFAULT 'Pending'")
        conn.commit()
    except sqlite3.OperationalError as e:
        if "duplicate column name" not in str(e).lower():
            st.error(f"Database error: {e}")
    except sqlite3.Error as e:
        st.error(f"Database error: {e}")

ensure_status_column()
conn.commit()

def update_score_and_rerun(student, quiz_id, score):
    try:
        c.execute("UPDATE scores SET score = ?, evaluated_by = ?, status = 'Assigned' WHERE student = ? AND quiz_id = ?",
                  (score, st.session_state.username, student, quiz_id))
        c.execute("UPDATE marks SET score = ?, status='Assigned' WHERE student_id = ? AND quiz_title = ?", (score, student, "Untitled"))
        conn.commit()
        st.success(f"✅ Score submitted for {student} (Quiz {quiz_id})")
        st.rerun()
    except sqlite3.Error as e:
        st.error(f"Database error: {e}")

def generate_mcqs(content, num_mcqs, difficulty):
    model = genai.GenerativeModel(model_name="gemini-1.5-flash")

    # Define different prompts for difficulty levels
    difficulty_prompts = {
        "Easy": f"Generate {num_mcqs} simple MCQs from the following content. Ensure basic conceptual questions with direct answers:\n\n{content}",
        "Medium": f"Generate {num_mcqs} MCQs from the following content. Include a mix of conceptual and application-based questions with some tricky distractors:\n\n{content}",
        "Hard": f"Generate {num_mcqs} challenging MCQs from the following content. Ensure complex application-based, inference, and analysis questions with strong distractors:\n\n{content}"
    }

    prompt = difficulty_prompts.get(difficulty, difficulty_prompts["Medium"])  # Default to Medium
    response = model.generate_content(prompt)
    
    if response and response.text:
        return response.text.strip()
    return ""

def fetch_consolidated_results():
    c.execute("""
        SELECT scores.student, scores.quiz_id, quizzes.title, scores.score
        FROM scores
        JOIN quizzes ON scores.quiz_id = quizzes.id
        WHERE scores.score IS NOT NULL
    """)
    results = c.fetchall()
    df = pd.DataFrame(results, columns=["Student", "Quiz ID", "Quiz Title", "Score"])
    return df

# Function to generate PDF of consolidated results
def generate_results_pdf(df):
    pdf = FPDF()
    pdf.set_font("Arial", size=12)
    pdf.add_page()

    pdf.cell(200, 10, txt="Consolidated Results", ln=True, align='C')

    for index, row in df.iterrows():
        pdf.cell(200, 10, txt=f"Student: {row['Student']}, Quiz ID: {row['Quiz ID']}, Score: {row['Score']}", ln=True)

    filename = "consolidated_results.pdf"
    pdf.output(filename)
    return filename

# Function to generate summary data
def generate_summary(df):
    summary_df = df.groupby("Quiz Title").agg(
        Students_Attended=("Student", "nunique"),
        Highest_Score=("Score", "max"),
        Lowest_Score=("Score", "min")
    ).reset_index()
    return summary_df

# Function to plot charts
def plot_charts(summary_df):
    st.write("### Attendance by Quiz Title")
    fig = px.bar(
        summary_df, 
        x="Quiz Title", 
        y="Students_Attended", 
        color="Students_Attended", 
        title="Number of Students Attended per Quiz"
    )
    fig.update_layout(xaxis_title="Quiz Title", yaxis_title="Number of Students", height=400,yaxis=dict(
            tickmode='linear',  # Ensures linear increments
            dtick=1             # Sets increment to 1
        ))
    st.plotly_chart(fig)

    st.write("### Score Distribution")
    fig = px.bar(
        summary_df, 
        x="Quiz Title", 
        y=["Highest_Score", "Lowest_Score"],
        barmode='group',
        title="Score Distribution per Quiz"
    )
    fig.update_layout(xaxis_title="Quiz Title", yaxis_title="Score", height=400)
    st.plotly_chart(fig)


# Function to generate audio for MCQs
def generate_mcq_audio(question, options):
    text = question + " " + " ".join(options)
    tts = gTTS(text=text, lang="en")
    filename = f"mcq_{uuid.uuid4().hex}.mp3"
    tts.save(filename)
    return filename

# Function to extract text from uploaded files
def extract_text_from_file(uploaded_file):
    if uploaded_file.type == "application/pdf":
        pdf_reader = PdfReader(uploaded_file)
        return "\n".join([page.extract_text() for page in pdf_reader.pages if page.extract_text()])
    elif uploaded_file.type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        doc = Document(uploaded_file)
        return "\n".join([para.text for para in doc.paragraphs])
    elif uploaded_file.type == "text/plain":
        return uploaded_file.getvalue().decode("utf-8")
    return ""




# Function to save MCQs as PDF
def save_mcqs_to_pdf(mcqs_text, title):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)  # Use built-in font (fixes missing font issue)

    pdf.cell(200, 10, txt=title, ln=True, align='C')
    pdf.multi_cell(0, 10, mcqs_text)

    filename = f"quiz_{uuid.uuid4().hex}.pdf"
    pdf.output(filename, "F").encode("utf-8")  # Save file
    return filename

# User Registration Function
def register_user(username, password, role):
    hashed_password = bcrypt.hashpw(password.encode(), bcrypt.gensalt())
    try:
        c.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)", (username, hashed_password, role))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False

# User Authentication Function
def authenticate_user(username, password):
    c.execute("SELECT password, role FROM users WHERE username = ?", (username,))
    user = c.fetchone()
    if user and bcrypt.checkpw(password.encode(), user[0]):
        return user[1]  
    return None

# Function to parse MCQs safely
def parse_mcqs(mcq_text):
    try:
        mcq_list = mcq_text.strip().split("\n")
        parsed_questions = []
        i = 0

        while i < len(mcq_list):
            question = mcq_list[i].strip()
            if not question or not question[0].isdigit():
                i += 1
                continue

            i += 1
            options = []
            while i < len(mcq_list) and len(options) < 4:
                option = mcq_list[i].strip()
                if option.startswith(("a)", "b)", "c)", "d)")):
                    options.append(option)
                i += 1

            if len(options) == 4:
                parsed_questions.append((question, options))

        return parsed_questions
    except Exception as e:
        st.error(f"⚠ Error parsing MCQs: {e}")
        return []

def evaluate_student_answers(student_answers, correct_answers):
    score = 0
    st.write("Correct Answers:", correct_answers)
    st.write("Student Answers:", student_answers)

    for q, student_answer in student_answers.items():
        if q in correct_answers:
            if student_answer == correct_answers[q]:
                score += 1
                st.write(f"Question {q}:Correct")
            else:
                st.write(f"Question {q}: Incorrect(Expected:{correct_answers[q]},Got:{student_answer})")
    return score


# Custom CSS for modern UI
def load_css():
    st.markdown("""
    <style>
    /* Main theme colors */
    :root {
        --primary-color: #0B6E4F;
        --secondary-color: #08A045;
        --accent-color: #0DF5E3;
        --background-color: #F5F5F5;
        --text-color: #333333;
    }
    
    /* Body styling */
    body {
        background-color: var(--background-color);
        color: var(--text-color);
        font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
    }
    
    /* Container styling for login/register cards */
    .auth-container {
        max-width: 400px;
        margin: 0 auto;
        padding: 20px;
        background-color: white;
        border-radius: 12px;
        
    }
    
    /* Form elements */
    div[data-testid="stTextInput"] input {
        border-radius: 15px;
        border: 1px solid #e0e0e0;
        padding: 5px 5px;
        background-color: rgba(240, 255, 240, 0.5);
        transition: all 0.3s;
        width: 80%; 
                
    }
    
    div[data-testid="stTextInput"] input:focus {
        border-color: var(--primary-color);
        box-shadow: 0 0 0 2px rgba(11, 110, 79, 0.2);
    }
    
    .stButton > button {
        border-radius: 20px;
        background-color: var(--primary-color);
        color: white;
        font-weight: 500;
        padding: 8px 16px;
        border: none;
        transition: all 0.3s;
        width: 100%;
    }
    
    .stButton > button:hover {
        background-color: var(--secondary-color);
        box-shadow: 0 4px 8px rgba(0, 0, 0, 0.1);
        transform: translateY(-1px);
    }
    
    /* Logo and header styling */
    .logo-container {
        text-align: center;
        margin-bottom: 20px;
    }
    
    .logo {
        width: 80px;
        height: 80px;
        margin: 0 auto;
        border-radius: 50%;
        background-color: var(--primary-color);
        display: flex;
        align-items: center;
        justify-content: center;
        color: white;
        font-size: 28px;
    }
    
    h1, h2, h3 {
        color: var(--primary-color);
        font-weight: 600;
    }
    
    .welcome-text {
        text-align: center;
        margin-bottom: 20px;
        font-size: 24px;
        font-weight: 600;
        color: var(--primary-color);
    }
    
    .subtitle {
        text-align: center;
        margin-bottom: 20px;
        font-size: 14px;
        color: #666;
    }
    
    /* Helper text for signup link */
    .helper-text {
        text-align: center;
        margin-top: 15px;
        font-size: 14px;
        color: #666;
    }
    
    .helper-text a {
        color: var(--primary-color);
        text-decoration: none;
        font-weight: 500;
    }
    
    /* Success/error messages */
    div[data-testid="stAlert"] {
        border-radius: 8px;
        margin-top: 16px;
    }
    
    /* Dashboard specific styling */
    .dashboard-card {
        background-color: white;
        border-radius: 8px;
        padding: 16px;
        margin-bottom: 16px;
        box-shadow: 0 2px 5px rgba(0, 0, 0, 0.05);
    }
    
    /* Sidebar styling */
    .sidebar .sidebar-content {
        background-color: var(--primary-color);
        color: white;
    }
    
    /* Custom styling for selectbox */
    div[data-testid="stSelectbox"] > div > div {
        border-radius: 20px;
        background-color: rgba(240, 255, 240, 0.5);
    }
    
    /* Footer */
    .footer {
        text-align: center;
        margin-top: 40px;
        font-size: 12px;
        color: #999;
    }
    </style>
    """, unsafe_allow_html=True)

# Streamlit Page Configuration
st.set_page_config(
    page_title="Smart Quiz For Learners",
    layout="wide",
    initial_sidebar_state="collapsed"
)
load_css()

# Initialize session state variables
if "page" not in st.session_state:
    st.session_state.page = "login"

# Conditional rendering based on page state
if st.session_state.page == "login":
    # Create a centered container for login
    col1, col2, col3 = st.columns([2, 1, 2])
    
    with col2:
        st.markdown('<div class="auth-container">', unsafe_allow_html=True)

        
        
        # Logo and welcome text
        st.markdown('''
        <div class="logo-container">
            <div class="logo">📚</div>
        </div>
        <div class="welcome-text">Welcome Back!</div>
        <div class="subtitle">Login to your account to continue</div>
        ''', unsafe_allow_html=True)
        
        # Login form
        username = st.text_input("Username", key="username_input", placeholder="Enter your username")
        password = st.text_input("Password", type="password", key="password_input", placeholder="Enter your password")
        
        # Forgot password link
        st.markdown('<div style="text-align: right; margin-top: -15px; margin-bottom: 15px;"><a href="#" style="color: #0B6E4F; font-size: 12px; text-decoration: none;">Forgot your password?</a></div>', unsafe_allow_html=True)
        
        if st.button("Log In"):
            if username and password:
                role = authenticate_user(username, password)
                if role:
                    st.session_state.username = username
                    st.session_state.role = role
                    st.session_state.page = "dashboard"
                    st.rerun()
                else:
                    st.error("❌ Invalid username or password.")
            else:
                st.error("❌ Please enter both username and password.")
        
        # Sign up helper text
        st.markdown('<div class="helper-text">Don\'t have an account? <a href="#" onclick="document.querySelector(\'button:contains(Register)\').click()"</a></div>', unsafe_allow_html=True)
        
       
        col1, col2, col3 = st.columns([0.5, 1, 0.5])
        with col2:
            if st.button("Sign up", key="signup_btn"):
                st.session_state.page = "register"
                st.rerun()
        
        st.markdown('</div>', unsafe_allow_html=True)

elif st.session_state.page == "register":
    # Create a centered container for registration
    col1, col2, col3 = st.columns([2, 2.5, 2])
    
    with col2:
        st.markdown('<div class="auth-container">', unsafe_allow_html=True)


        
        # Add platform title and subtitle here
        st.markdown('<h2 style="text-align: center;">Smart Quiz For Learners</h2>', unsafe_allow_html=True)
        st.markdown('<h3 style="text-align: center;">Your Knowledge, Your Score – Let\'s Go!</h3>', unsafe_allow_html=True)
        
        
        # Logo and welcome text
        st.markdown('''
        <div class="logo-container">
            <div class="logo">📝</div>
        </div>
        <div class="welcome-text">Create Account</div>
        <div class="subtitle">Sign up to get started with Smart Quiz</div>
        ''', unsafe_allow_html=True)
        
        # Registration form
        new_user = st.text_input("Username", key="new_user", placeholder="Choose a username")
        new_pass = st.text_input("Password", type="password", key="new_pass", placeholder="Create a password")
        role = st.selectbox("Role", ["Teacher", "Student"], key="role_select")
        
        if st.button("Sign Up", key="register_btn"):
            if new_user and new_pass:
                if register_user(new_user, new_pass, role):
                    st.session_state.registered = True
                    st.success("✅ Registration successful! Please login.")
                else:
                    st.error("❌ Username already exists.")
            else:
                st.error("❌ Please enter both username and password.")
        
        # Login helper text
        st.markdown('<div class="helper-text">Already have an account? <a href="#" onclick="document.querySelector(\'button:contains(Login)\').click()"></a></div>', unsafe_allow_html=True)
        
        col1, col2, col3 = st.columns([0.5, 1, 0.5])
        with col2:
            if st.button("Login", key="login_nav_btn"):
                st.session_state.page = "login"
                st.rerun()


        st.markdown('</div>', unsafe_allow_html=True)

elif st.session_state.page == "dashboard":
    # Sidebar navigation
    with st.sidebar:
        st.markdown(f'''
        <div style="padding: 16px; color: Black;">
            <h3>👋 Hello, {st.session_state.username}</h3>
            <p>Role: {st.session_state.role}</p>
        </div>
        ''', unsafe_allow_html=True)
        
        if st.button("Logout", key="logout_btn"):
            st.session_state.clear()
            st.session_state.page = "login"
            st.rerun()

    # Main dashboard content
    st.markdown(
    '<h1 style="text-align: center; font-size: 36px; color: #008a20;">📝 Smart Quiz For Learners</h1>', 
    unsafe_allow_html=True
)
    st.markdown("<h3 style='text-align: center;  font-size:20px;color: #646970;'>Your Knowledge, Your Score – Let's Go!</h3>", unsafe_allow_html=True)

    if st.session_state.role == "Teacher":
        st.markdown(
        '<h2 style="font-size: 24px; color: #005c12;">📚 Teacher Dashboard</h2>', 
        unsafe_allow_html=True
    )
        # Teacher dashboard with improved UI
        st.markdown("""
    <style>
    .stTabs [data-baseweb="tab-list"] {
        gap: 20px; /* Adds space between tabs */
    }
    .stTabs [data-baseweb="tab"] {
        padding: 10px 20px; /* Adds padding inside each tab */
        font-size: 16px; /* Adjust font size */
    }
    .stTabs [data-baseweb="tab"]:hover {
        background-color: #f0f0f0; /* Adds hover effect */
    }
    </style>
    """, unsafe_allow_html=True)
        

        
        
        #tabs = st.tabs(["Upload Lecture", "Create Quiz", "Evaluate Submissions"])
        tabs = st.tabs([
    "📤 Upload Lecture", 
    "📝 Create Quiz", 
    "📊 Evaluate Submissions",
    "📊 Consolidated Results View"
])
        
        with tabs[0]:
            # Upload Lecture
            st.markdown('<div class="dashboard-card">', unsafe_allow_html=True)
            st.markdown(
            '<h3 style="font-size: 20px; color: #005c12;">Upload a Lecture</h3>', 
            unsafe_allow_html=True)
        
            lecture_title = st.text_input("Lecture Title:")
            lecture_content = st.text_area("Lecture Content:")

            if st.button("Upload Lecture", key="upload_lecture_btn"):
                if lecture_title and lecture_content:
                    c.execute("INSERT INTO lectures (teacher, title, content) VALUES (?, ?, ?)", 
                            (st.session_state.username, lecture_title, lecture_content))
                    conn.commit()
                    st.success("✅ Lecture uploaded successfully!")
                else:
                    st.error("❌ Please enter both a title and content.")
            st.markdown('</div>', unsafe_allow_html=True)
        
        with tabs[1]:
            # Create and Post MCQs
            st.markdown('<div class="dashboard-card">', unsafe_allow_html=True)
            st.subheader("Create and Post MCQs")
            quiz_title = st.text_input("Quiz Title:")
            num_mcqs = st.number_input("Number of MCQs to Generate:", min_value=1, max_value=20, value=5)
            
            col1, col2 = st.columns(2)
            with col1:
                uploaded_file = st.file_uploader("Choose a file", type=["pdf", "docx", "txt"])
            with col2:
                st.write("Supported formats: PDF, DOCX, TXT")
                st.write("Maximum file size: 200MB")
            
            manual_input = st.text_area("Or Enter a Topic/Text (if no file uploaded)", "")
            
            mcq_content = ""
            if uploaded_file:
                extracted_text = extract_text_from_file(uploaded_file)
            elif manual_input.strip():
                extracted_text = manual_input
            else:
                extracted_text = ""

            if extracted_text:
                with st.expander("View Extracted Content", expanded=False):
                    st.text_area("Content:", extracted_text, height=200)
                
                if "mcqs_generated" not in st.session_state:
                    st.session_state.mcqs_generated = ""
                    st.session_state.quiz_generated = False
                    st.session_state.quiz_posted = False
                if "generated_mcqs" not in st.session_state:
                    st.session_state.generated_mcqs = ""
                if "current_quiz_title" not in st.session_state:
                    st.session_state.current_quiz_title = ""
                if "quiz_posted" not in st.session_state:
                    st.session_state.quiz_posted = False
                
                difficulty = st.selectbox("Select Difficulty Level:", ["Easy", "Medium", "Hard"])
                
                if st.button("Generate MCQs", key="generate_mcqs_btn"):
                    if not quiz_title.strip():
                        st.error("Quiz title cannot be empty!")
                    elif not extracted_text:
                        st.error("No text extracted from the file. Please upload a valid file.")
                    else:
                        st.session_state.generated_mcqs = generate_mcqs(extracted_text, num_mcqs, difficulty)
                        st.session_state.current_quiz_title = quiz_title
                        st.session_state.selected_difficulty = difficulty
                        st.rerun()
                
                if st.session_state.generated_mcqs:
                    with st.expander("Review Generated MCQs", expanded=True):
                        st.text_area("MCQs:", st.session_state.generated_mcqs, height=300)
                    
                    col1, col2 = st.columns(2)
                    with col1:
                        if st.button("Regenerate MCQs", key="regenerate_mcqs_btn"):
                            st.session_state.generated_mcqs = generate_mcqs(manual_input, num_mcqs, st.session_state.selected_difficulty)
                            st.rerun()
                    with col2:
                        if st.button("Post Quiz", key="post_quiz_btn"):
                            try:
                                # Check if quiz title already exists
                                c.execute("SELECT 1 FROM quiz_titles WHERE title = ?", (st.session_state.current_quiz_title,))
                                if c.fetchone():
                                    st.error("⚠ A quiz with this topic has been posted already.")
                                else:
                                    # Insert into quiz_titles first
                                    c.execute("INSERT INTO quiz_titles (title) VALUES (?)", (st.session_state.current_quiz_title,))
                                    
                                    # Insert quiz into quizzes table
                                    c.execute("INSERT INTO quizzes (teacher, title, mcqs, answers) VALUES (?, ?, ?, ?)",
                                            (st.session_state.get("username", "Unknown"), 
                                            st.session_state.get("current_quiz_title", "Untitled"), 
                                            st.session_state.get("generated_mcqs", ""), ""))
                                    conn.commit()
                                    
                                    st.session_state.quiz_posted = True
                                    st.success("✅ Quiz successfully posted!")

                                    # Generate and provide a download link for PDF
                                    pdf_file = save_mcqs_to_pdf(st.session_state.generated_mcqs, st.session_state.current_quiz_title)
                                    with open(pdf_file, "rb") as file:
                                        st.download_button(
                                            label="📥 Download Quiz as PDF", 
                                            data=file, 
                                            file_name=pdf_file, 
                                            mime="application/pdf"
                                        )

                            except sqlite3.IntegrityError:
                                st.error("⚠ A quiz with this topic has been posted already.")
            st.markdown('</div>', unsafe_allow_html=True)
        
        with tabs[2]:
            # View & Evaluate Student Submissions
            st.markdown('<div class="dashboard-card">', unsafe_allow_html=True)
            st.subheader("📊 Evaluate Student Submissions")
            
            c.execute("SELECT student, quiz_id, student_answers FROM scores WHERE score IS NULL")
            submissions = c.fetchall()

            if submissions:
                for student, quiz_id, student_answers in submissions:
                    with st.expander(f"📝 {student} - Quiz {quiz_id}", expanded=False):
                        formatted_answers = json.loads(student_answers)

                        for q, ans in formatted_answers.items():
                            st.write(f"Q{q}: {ans}")
                        unique_key = f"score_{student}{quiz_id}{uuid.uuid4().hex}"
                        score = st.number_input(f"Assign Score for {student}:", min_value=0, max_value=100, step=1, key=unique_key)
                        if st.button(f"Submit Score for {student} - Quiz {quiz_id}", key=f"submit_{unique_key}"):
                            update_score_and_rerun(student, quiz_id, score)
            else:
                st.info("No pending submissions to evaluate.")
            st.markdown('</div>', unsafe_allow_html=True)
        
        with tabs[3]:
            # Consolidated Results
            st.markdown('<div class="dashboard-card">', unsafe_allow_html=True)
        
            st.subheader("📊 Consolidated Results View")
            df = fetch_consolidated_results()
            st.write("### Quiz Summary")
            summary_df = generate_summary(df)
            st.dataframe(summary_df)

            if not df.empty:
                st.dataframe(df)
                # Show charts
                plot_charts(summary_df)

                # Generate PDF button
                if st.button("Download Consolidated Results as PDF"):
                    pdf_file = generate_results_pdf(df)
                    with open(pdf_file, "rb") as file:
                        st.download_button(
                            label="📥 Download Results PDF",
                            data=file,
                            file_name=pdf_file,
                            mime="application/pdf"
                        )
            else:
                st.info("No results available yet.")

    elif st.session_state.role == "Student":
        # Student dashboard with improved UI
        st.subheader("📖 Student Dashboard")
        st.markdown("""
    <style>
    .stTabs [data-baseweb="tab-list"] {
        gap: 20px; /* Adds space between tabs */
    }
    .stTabs [data-baseweb="tab"] {
        padding: 10px 20px; /* Adds padding inside each tab */
        font-size: 16px; /* Adjust font size */
    }
    .stTabs [data-baseweb="tab"]:hover {
        background-color: #f0f0f0; /* Adds hover effect */
    }
    </style>
    """, unsafe_allow_html=True)


        
        #tabs = st.tabs(["Available Lectures", "Attempt Quiz", "My Results"])
        tabs = st.tabs([
    "📚 Available Lectures", 
    "📝 Attempt Quiz", 
    "📊 My Results"
])

        
        with tabs[0]:
            # View Lectures
            st.markdown('<div class="dashboard-card">', unsafe_allow_html=True)
            st.subheader("Browse Available Lectures")
            
            c.execute("SELECT title, content FROM lectures")
            lectures = c.fetchall()

            if lectures:
                for title, content in lectures:
                    with st.expander(f"📚 {title}", expanded=False):
                        st.write(content)
            else:
                st.info("No lectures available yet. Check back later!")
            st.markdown('</div>', unsafe_allow_html=True)
         
        with tabs[1]:
            # Attempt a Quiz
            st.markdown('<div class="dashboard-card">', unsafe_allow_html=True)
            st.subheader("Attempt a Quiz")
            
            c.execute("SELECT id, title, mcqs, answers FROM quizzes")
            quizzes = c.fetchall()

            c.execute("SELECT quiz_title FROM marks WHERE student_id = ?", (st.session_state.username,))
            attempted_quiz_titles = {row[0] for row in c.fetchall()}
            unattempted_quizzes = [q for q in quizzes if q[1] not in attempted_quiz_titles]
            attempted_quizzes = [q for q in quizzes if q[1] in attempted_quiz_titles]

            # Display summary of quizzes with improved styling
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Total Quizzes", len(quizzes))
            with col2:
                st.metric("Attempted", len(attempted_quizzes))
            with col3:
                st.metric("Remaining", len(unattempted_quizzes))

            if unattempted_quizzes:
                selected_quiz_title = st.selectbox(
                    "Select a Quiz to Attempt:",
                    [q[1] for q in unattempted_quizzes]
                )
                
                selected_quiz = next(q for q in unattempted_quizzes if q[1] == selected_quiz_title)
                
                with st.expander(f"Quiz: {selected_quiz[1]}", expanded=True):
                    parsed_questions = parse_mcqs(selected_quiz[2])
                    student_answers = {}
                    
                    for i, (question, options) in enumerate(parsed_questions):
                        st.markdown(f"{question}")
                        
                        c.execute("SELECT id FROM quizzes WHERE id=?", (selected_quiz[0],))
                        quiz_id_row = c.fetchone()
                        quiz_id = quiz_id_row[0] if quiz_id_row else None 
                        
                        key = f"q_{selected_quiz[0]}{i}{st.session_state.username}"
                        if key not in st.session_state:
                            st.session_state[key] = options[0]
                        
                        selected_option = st.radio(f"Select an option for Q{i+1}:", options, key=key)
                        student_answers[i] = selected_option

                    c.execute("SELECT id FROM quizzes WHERE id=?", (selected_quiz[0],))
                    quiz_id_row = c.fetchone()
                    quiz_id = quiz_id_row[0] if quiz_id_row else None

                    if st.button(f"Submit Answers", key=f"submit_answers_{selected_quiz[0]}"):
                        if len(student_answers) < len(parsed_questions):
                            st.error("⚠ Please answer all questions before submitting!")
                        else:
                            if quiz_id is not None:
                                student_response = json.dumps(student_answers)
                                c.execute("REPLACE INTO scores (student, quiz_id, student_answers) VALUES (?, ?, ?)",
                                        (st.session_state.username, quiz_id, student_response))
                                conn.commit()
                                st.success("✅ Answers submitted for evaluation!")
                                #st.balloons()
                            else:
                                st.error("⚠ Quiz ID not found!")
            else:
                st.info("🎉 You have attempted all available quizzes!")
            st.markdown('</div>', unsafe_allow_html=True)
            
        with tabs[2]:
            # View Results
            st.markdown('<div class="dashboard-card">', unsafe_allow_html=True)
            st.subheader("My Quiz Results")
            
            c.execute("""
                SELECT q.title, s.score, s.status
                FROM scores s
                JOIN quizzes q ON s.quiz_id = q.id
                WHERE s.student = ?
            """, (st.session_state.username,))
            import pandas as pd
            results = c.fetchall()
            print(results)
            
            if results:

                #import pandas as pd
                df = pd.DataFrame(results, columns=["Quiz Title", "Score","Status"])
    
                # Display the DataFrame without the index column
                df["Score"] = df["Score"].fillna("Pending")
                st.dataframe(df[["Quiz Title", "Score"]], hide_index=True)
                
            else:
                st.info("You haven't attempted any quizzes yet.")

# # Footer
# st.markdown('''
# <div class="footer">
#     &copy; 2025 Smart Quiz For Learners. All rights reserved. | 
#     <a href="#" style="color: #0B6E4F; text-decoration: none;">Privacy Policy</a> | 
#     <a href="#" style="color: #0B6E4F; text-decoration: none;">Terms of Service</a> | 
#     <a href="#" style="color: #0B6E4F; text-decoration: none;">Contact Us</a>
# </div>
# ''', unsafe_allow_html=True)
