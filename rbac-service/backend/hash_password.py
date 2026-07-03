from app.auth.password import get_password_hash

password = "Manager@123"

hashed = get_password_hash(password)

print("\nHashed Password:\n")
print(hashed)