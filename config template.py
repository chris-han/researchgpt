OPENAI_API_KEY= 'sk-'
BLOB_CONNECTION_STRING= 'DefaultEndpointsProtocol=https;EndpointSuffix=core.windows.net'
CONTAINER_NAME= 'papers'

API_TYPE='azure'
API_VERSION='2022-12-01' #this may change in the future
AZURE_OPENAI_KEY=''
API_BASE='' #your endpoint should look like the following https://YOUR_RESOURCE_NAME.openai.azure.com/  #for openai API: https://api.openai.com/v1/completions
COMPLETION_MODEL='text-davinci-003' #This will correspond to the custom name you chose for your deployment when you deployed a model.
EMBEDDING_MODEL="text-embedding-ada-002"
#EMBEDDING_GET_MODEL ='text-similarity-ada-001'