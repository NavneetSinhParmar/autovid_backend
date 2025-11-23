# autovid_backend
Basic step Of run this app
# Create Virtual Environment (Optional)
python -m venv venv
source venv/bin/activate    # macOS/Linux
venv\Scripts\activate       # Windows

# Install nacessary Libraries
pip install -r requirements.txt

# change Mango URI: (Paste Your Mongo server URI)
MONGO_URI = "mongodb+srv://<username>:<password>@<cluster>/<db_name>?retryWrites=true&w=majority"

pip install python-multipart