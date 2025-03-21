from flask import Flask, request, render_template
from io import BytesIO
from PyPDF2 import PdfReader
import pandas as pd
from openai.embeddings_utils import get_embedding, cosine_similarity
import openai
import os
import requests
from flask_cors import CORS
#from _md5 import md5
import hashlib
#from google.cloud import storage
from azure.storage.blob import BlobServiceClient, BlobClient, ContainerClient
import config as cfg
from openai.error import InvalidRequestError
import backoff

app = Flask(__name__)
# db=redis.from_url(os.environ['REDISCLOUD_URL'])
# db = redis.StrictRedis(host='localhost', port=6379, db=0)

# Set the connection string and container name
connection_string = cfg.BLOB_CONNECTION_STRING
container_name = cfg.CONTAINER_NAME

openai.api_base = cfg.API_BASE
openai.api_key = cfg.AZURE_OPENAI_KEY

#only azure api need below two lines
openai.api_type = cfg.API_TYPE
openai.api_version = cfg.API_VERSION



CORS(app)

class Chatbot():
    
    def extract_text(self, pdf):
        print("Parsing paper")
        number_of_pages = len(pdf.pages)
        print(f"Total number of pages: {number_of_pages}")
        paper_text = []
        for i in range(number_of_pages):
            page = pdf.pages[i]
            page_text = []

            def visitor_body(text, cm, tm, fontDict, fontSize):
                x = tm[4]
                y = tm[5]
                # ignore header/footer
                if (y > 50 and y < 720) and (len(text.strip()) > 1):
                    page_text.append({
                    'fontsize': fontSize,
                    'text': text.strip().replace('\x03', ''),
                    'x': x,
                    'y': y
                    })

            _ = page.extract_text(visitor_text=visitor_body)

            blob_font_size = None
            blob_text = ''
            processed_text = []

            for t in page_text:
                if t['fontsize'] == blob_font_size:
                    blob_text += f" {t['text']}"
                    if len(blob_text) >= 2000:
                        processed_text.append({
                            'fontsize': blob_font_size,
                            'text': blob_text,
                            'page': i
                        })
                        blob_font_size = None
                        blob_text = ''
                else:
                    if blob_font_size is not None and len(blob_text) >= 1:
                        processed_text.append({
                            'fontsize': blob_font_size,
                            'text': blob_text,
                            'page': i
                        })
                    blob_font_size = t['fontsize']
                    blob_text = t['text']
                paper_text += processed_text
        print("Done parsing paper")
        # print(paper_text)
        return paper_text

    def create_df(self, pdf):
        print('Creating dataframe')
        filtered_pdf= []
        for row in pdf:
            if len(row['text']) < 30:
                continue
            filtered_pdf.append(row)
        df = pd.DataFrame(filtered_pdf)
        # print(df.shape)
        # remove elements with identical df[text] and df[page] values
        df = df.drop_duplicates(subset=['text', 'page'], keep='first')
        df['length'] = df['text'].apply(lambda x: len(x))
        print('Done creating dataframe')
        return df

    def embeddings(self, df):
        print('Calculating embeddings')
        openai.api_key = cfg.AZURE_OPENAI_KEY
        embedding_model = cfg.EMBEDDING_MODEL
        print('book length: ', len(df.text))
        embeddings = df.text.apply([lambda x: get_embedding(x, engine=embedding_model)])
        df["embeddings"] = embeddings
        print('Done calculating embeddings')
        return df

    def search(self, df, query, n=3, pprint=True):
        query_embedding = get_embedding(
            query,
            engine=cfg.EMBEDDING_MODEL
        )
        df["similarity"] = df.embeddings.apply(lambda x: cosine_similarity(x, query_embedding))
        
        results = df.sort_values("similarity", ascending=False, ignore_index=True)
        # make a dictionary of the the first three results with the page number as the key and the text as the value. The page number is a column in the dataframe.
        results = results.head(n)
        global sources 
        sources = []
        for i in range(n):
            # append the page number and the text as a dict to the sources list
            sources.append({'Page '+str(results.iloc[i]['page']): results.iloc[i]['text'][:150]+'...'})
        print(sources)
        return results.head(n)
    
    def create_prompt(self, df, user_input):
        result = self.search(df, user_input, n=3)
        print(result)
        prompt = """You are an expert in summarizing scientific papers. 
        You are given a query and a series of text embeddings.
        You must take the given embeddings and return a very detailed summary of the paper that answers the query.
            
            Given the question: """+ user_input + """
            
            and the following embeddings as data: 
           
            1.""" + str(result.iloc[0]['text']) + """
            2.""" + str(result.iloc[1]['text']) + """
            3.""" + str(result.iloc[2]['text']) 


        print('Done creating prompt', len(prompt))
        return prompt


    @backoff.on_exception(backoff.expo, ValueError, max_tries=2)
    def gpt(self, prompt):        
        prompt=prompt[:1000]+""""
        
        Return a detailed answer based on the paper:"""
        #openai.api_key = cfg.AZURE_OPENAI_KEY

        print('Sending request to GPT-3: ', len(prompt))
        r = openai.Completion.create(engine=cfg.COMPLETION_MODEL, prompt=prompt, temperature=0.0, max_tokens=1500)
        answer = r.choices[0]['text']
        print('Done sending request to GPT-3')
        response = {'answer': answer, 'sources': sources}
        # except InvalidRequestError:
        #     prompt=prompt[:1000]
        #     print('promot reduced to: ', len(prompt))
        #     raise ValueError

        return response

@app.route("/", methods=["GET", "POST"])
def index():
    return render_template("index.html")


@app.route("/process_pdf", methods=['POST'])
def process_pdf():
    print("Processing pdf")
    print(request)
    # print('the data')
    # print(request.data)
    file = request.data

    key = hashlib.md5(file).hexdigest()
    print(key)
    # Create a Cloud Storage client.
    #gcs = storage.Client()
    # Create a BlobServiceClient object
    blob_service_client = BlobServiceClient.from_connection_string(connection_string)
    name = key+'.json'

    # Get the bucket that the file will be uploaded to.
    #bucket = gcs.get_bucket(CLOUD_STORAGE_BUCKET)
    # Create a ContainerClient object
    container_client = blob_service_client.get_container_client(container_name)
    # Check if the file already exists
    #if bucket.blob(name).exists():
    # Check if the blob already exists in the container
    blob_client = container_client.get_blob_client(name)
    if blob_client.exists():
        print("File already exists")
        print("Done processing pdf")
        return {"key": key}

    else:
        pdf = PdfReader(BytesIO(file))
        chatbot = Chatbot()
        paper_text = chatbot.extract_text(pdf)
        df = chatbot.create_df(paper_text)
        df = chatbot.embeddings(df)
        
        # Create a new blob and upload the file's content.
        #blob = bucket.blob(name)
        #blob.upload_from_string(df.to_json(), content_type='application/json')

        # Upload the data to the blob
        blob_client.upload_blob (df.to_json(), overwrite=True)
        # if db.get(key) is None:
        #     db.set(key, df.to_json())
        print("Done processing pdf")
        return {"key": key}

@app.route("/download_pdf", methods=['POST'])
def download_pdf():
    print("Downloading pdf")
    print(request)
    print(request.json['url'])
    chatbot = Chatbot()
    url = request.json['url']
    r = requests.get(str(url))    
    file = r.content
    print("Downloading pdf")
    print(r.status_code)
    # print(r.content)
    
    key = hashlib.md5(file).hexdigest()
    # Create a Cloud Storage client.
    blob_service_client = BlobServiceClient.from_connection_string(connection_string)
    name = key+'.json'
    container_client = blob_service_client.get_container_client(container_name)
    # Get the bucket that the file will be uploaded to.
    blob_client = container_client.get_blob_client(name)
    if blob_client.exists():
        print("File already exists")
        print("Done processing pdf")
        return {"key": key}
    else:
        pdf = PdfReader(BytesIO(file))
        paper_text = chatbot.extract_text(pdf)
        df = chatbot.create_df(paper_text)
        df = chatbot.embeddings(df)

        # Create a new blob and upload the file's content.
        blob_client.upload_blob (df.to_json(), overwrite=True)
        print("Done processing pdf")
        return {"key": key}

@app.route("/reply", methods=['POST'])
def reply():
    chatbot = Chatbot()
    key = request.json['blob-key']
    query = request.json['query']
    query = str(query)
    print(query)
    # df = pd.read_json(BytesIO(db.get(key)))
    blob_service_client = BlobServiceClient.from_connection_string(connection_string)
    name = key+'.json'
    container_client = blob_service_client.get_container_client(container_name)
    # Get the bucket that the file will be uploaded to.
    blob_client = container_client.get_blob_client(name)
    # Download the data from the blob
    data_json = blob_client.download_blob().content_as_text()
    
    df = pd.read_json(data_json, orient="records")
    print(df.head(5))
    prompt = chatbot.create_prompt(df, query)
    response = chatbot.gpt(prompt)
    print(response)
    return response, 200

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=8080, debug=True)
