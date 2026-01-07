from app.core.config import settings

print(f"POSTGRES_PORT type: {type(settings.POSTGRES_PORT)}")
print(f"POSTGRES_PORT value: '{settings.POSTGRES_PORT}'")
print(f"DATABASE_URL_SYNC: '{settings.DATABASE_URL_SYNC}'")
