# autovid_backend

Basic step Of run this app

# Create Virtual Environment (Optional)

python -m venv venv
source venv/bin/activate # macOS/Linux
source venv/Scripts/activate # Windows

# Install nacessary Libraries

pip install -r requirements.txt

uvicorn main:app --reload
uvicorn app.main:app --reload

# change Mango URI: (Paste Your Mongo server URI)

MONGO_URI = "mongodb+srv://<username>:<password>@<cluster>/<db_name>?retryWrites=true&w=majority"

pip install python-multipart
ffmpeg -v debug -i C:\Users\viren\Downloads\videodata\datadummy\sample-5s.mp4 output.mp4.
