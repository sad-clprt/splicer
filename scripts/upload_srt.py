import os
from dotenv import load_dotenv
load_dotenv(dotenv_path="/home/samir/Projects/splicer/.env", override=True)
from app.database import SessionLocal
from app.models import Film, Asset
from app.s3 import get_s3_client, VOLUME_ID, S3_ENDPOINT, s3_key_for_film

film_id = "945c6475-a629-4140-9968-9135d716565d"
db = SessionLocal()
film = db.query(Film).filter(Film.id == film_id).first()
print("film", film.title if film else "not found")

srt_path = "/home/samir/Downloads/Films/I Am Legend AlTERNATE ENDING (2007) [1080p]/I.Am.Legend.ALTERNATE.ENDING.2007.1080p.BrRip.x264.srt"
s3 = get_s3_client()
bucket = VOLUME_ID
s3_key = s3_key_for_film(str(film_id), "I.Am.Legend.srt")
print("s3_key", s3_key, "bucket", bucket)
lst0 = s3.list_objects_v2(Bucket=bucket, Prefix=s3_key)
print("before list", lst0.get("KeyCount"))

print("uploading...")
s3.upload_file(srt_path, bucket, s3_key)
print("uploaded")
lst = s3.list_objects_v2(Bucket=bucket, Prefix=s3_key)
print("after list", lst.get("KeyCount"), lst["Contents"][0]["Size"] if lst.get("Contents") else "none")
existing = db.query(Asset).filter(Asset.s3_key == s3_key).first()
if existing:
    print("asset exists", existing.id, existing.status)
    existing.status = "available"
    existing.size_bytes = lst["Contents"][0]["Size"]
    # need to ensure kind is subtitle
    existing.kind = "subtitle"  # type: ignore
    db.commit()
    print("updated")
else:
    asset = Asset(
        film_id=film.id,  # type: ignore
        kind="subtitle",  # type: ignore
        runpod_volume_id=bucket,
        s3_key=s3_key,
        s3_endpoint=S3_ENDPOINT,
        datacenter=os.getenv("AWS_S3_REGION", "EU-RO-1"),
        size_bytes=lst["Contents"][0]["Size"],
        status="available",
    )
    db.add(asset)
    db.commit()
    print("created asset", asset.id)

for a in db.query(Asset).filter(Asset.film_id == film_id).order_by(Asset.created_at).all():
    print("asset", a.kind, a.s3_key, a.size_bytes, a.status)
