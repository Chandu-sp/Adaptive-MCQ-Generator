



import sqlite3

# Connect to the database
conn = sqlite3.connect("users.db")
c = conn.cursor()

# Delete all quizzes
c.execute("DELETE FROM quizzes")

# # Delete all student answers
c.execute("DELETE FROM scores")

c.execute("DELETE FROM lectures")
c.execute("DELETE FROM marks")

c.execute("DELETE FROM quiz_titles")


print("✅ All quizzes and student answers have been deleted successfully!")
