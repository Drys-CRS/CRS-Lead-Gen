from supabase import create_client

# Using the new local development keys
url = "http://127.0.0.1:54321"
key = "sb_publishable_ACJWlzQHlZjBrEguHvfOxg_3BJgxAaH"

print(f"✅ Target URL: {url}")
print(f"🔑 Key ends with: ...{key[-6:]}")
print("⏳ Attempting to connect to your local Supabase instance...")

try:
    supabase = create_client(url, key)
    response = supabase.table("leads").select("id").limit(1).execute()
    print("🎉 SUCCESS! Connection established and 'leads' table is accessible.")
except Exception as e:
    print(f"❌ DATABASE ERROR: {e}")