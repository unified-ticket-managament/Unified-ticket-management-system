import psycopg2

conn = psycopg2.connect(
    host="localhost",
    database="rbac_db",
    user="admin_user",
    password="admin123"
)

print("Database Connected Successfully!")

conn.close()