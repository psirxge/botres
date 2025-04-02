import requests

url = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"

payload={
  'scope': 'GIGACHAT_API_PERS'
}
headers = {
  'Content-Type': 'application/x-www-form-urlencoded',
  'Accept': 'application/json',
  'RqUID': '5f1be6fb-565b-40e1-b81f-de29bc9a90ad',
  'Authorization': 'Basic YjE3OWY2ODgtMTdjZi00MjEwLWE0OTMtYTVhZTEyZDk4YjRjOjQ4ZGYwY2E4LTk2YjgtNDc5Ny04MjhiLTljZGZiNzllOWYwZA=='
}

response = requests.request("POST", url, headers=headers, data=payload)

print(response.text)