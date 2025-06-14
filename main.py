from openai import OpenAI
import os
from dotenv import load_dotenv
from fastapi import FastAPI, Form, Request, WebSocket
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
import random
import json
from typing import Annotated

load_dotenv()

keywords = {
    "list": "Lists are mutable sequences in Python that can store multiple items.",
    "function": "Functions in Python are blocks of code that perform a specific task.",
    "loop": "Loops in Python allow you to iterate over data structures.",
    "array": "Arrays in JavaScript are used to store multiple values in a single variable.",
    "function in js": "Functions in JavaScript are reusable blocks of code.",
    "promise": "Promises in JavaScript handle asynchronous operations.",
    "class in java": "A class in Java is a blueprint for creating objects.",
    "interface": "Interfaces in Java define methods that classes must implement.",
    "vector": "Vectors in C++ are dynamic arrays that can resize automatically.",
    "class in cpp": "A class in C++ is a user-defined type that can contain data and functions."
}

def find_keywords(input_text, language):
    for keyword, explanation in keywords.items():
        if keyword in input_text.lower() and language.lower() in keyword:
            return explanation
    return None

neutral_phrases = ["Cool!", "Tell me more!", "Why do you think so?", "That's interesting!"]

def generate_neutral_response():
    return random.choice(neutral_phrases)

tasks = {
    "Python": ["Write a function that calculates the factorial of a number.",
               "Create a list and sort it in descending order."],
    "JavaScript": ["Write a function to reverse a string.",
                   "Create an array and filter out even numbers."],
    "Java": ["Write a class to represent a rectangle with area and perimeter methods.",
             "Implement a method to check if a string is a palindrome."],
    "C++": ["Write a function to swap two numbers using pointers.",
            "Create a vector and sort it in ascending order."]
}

def get_random_task(language):
    return random.choice(tasks.get(language, ["Write a simple program."]))

openai = OpenAI(api_key=os.getenv('OPENAI_API_SECRET_KEY'))
app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="templates")

chat_responses = {}
selected_language = "Python"
current_task = ""

@app.get("/", response_class=HTMLResponse)
async def chat_page(request: Request):
    return templates.TemplateResponse("home.html", {"request": request, "chat_responses": chat_responses.get(selected_language, [])})

@app.get("/chat", response_class=HTMLResponse)
async def get_chat_page(request: Request):
    return templates.TemplateResponse("chat.html", {"request": request, "selected_language": selected_language})

@app.get("/practice", response_class=HTMLResponse)
async def practice_page(request: Request):
    global current_task, selected_language
    selected_language = request.query_params.get("lang", selected_language)
    if not selected_language:
        selected_language = "Python"
    current_task = get_random_task(selected_language)
    return templates.TemplateResponse("practice.html", {
        "request": request,
        "selected_language": selected_language,
        "task_description": current_task
    })

@app.websocket("/ws")
async def chat(websocket: WebSocket):
    global selected_language, current_task
    await websocket.accept()

    chat_log = []

    while True:
        try:
            data = await websocket.receive_text()
            data_dict = json.loads(data)
            msg_type = data_dict.get('type', 'chat')
            user_input = data_dict.get('content', '')
            language = data_dict.get('language', 'Python')
            selected_language = language

            if not chat_log or chat_log[0]['content'] != (f'You are a {selected_language} tutor AI, '
                                                          f'dedicated to teaching users how to learn '
                                                          f'{selected_language} from scratch.'):
                chat_log = [
                    {'role': 'system',
                     'content': f'You are a {selected_language} tutor AI, dedicated to teaching '
                                f'users how to learn {selected_language} from scratch.'}
                ]

            if msg_type == 'change_language':
                current_task = get_random_task(selected_language)
                task_message = json.dumps({
                    'type': 'new_task',
                    'task': current_task,
                    'language': selected_language
                })
                await websocket.send_text(task_message)
                continue

            if msg_type == 'chat':
                chat_log.append({'role': 'user', 'content': user_input})

                if selected_language not in chat_responses:
                    chat_responses[selected_language] = []
                chat_responses[selected_language].append(user_input)

                keyword_response = find_keywords(user_input, selected_language)
                if keyword_response:
                    await websocket.send_text(keyword_response)
                    chat_responses[selected_language].append(keyword_response)
                    chat_log.append({'role': 'assistant', 'content': keyword_response})
                    continue

                try:
                    response = openai.chat.completions.create(
                        model='gpt-4o',
                        messages=chat_log,
                        temperature=0.6,
                        stream=True
                    )
                    ai_response = ''
                    for chunk in response:
                        if chunk.choices[0].delta.content is not None:
                            content = chunk.choices[0].delta.content
                            ai_response += content
                            await websocket.send_text(content)

                    chat_responses[selected_language].append(ai_response)
                    chat_log.append({'role': 'assistant', 'content': ai_response})

                except Exception as e:
                    print(f"OpenAI API error: {e}")
                    neutral_response = generate_neutral_response()
                    await websocket.send_text(neutral_response)
                    chat_responses[selected_language].append(neutral_response)
                    chat_log.append({'role': 'assistant', 'content': neutral_response})

            elif msg_type == 'code':
                prompt = (f"Check the following {selected_language} code for the task '{current_task}':"
                          f"\n{user_input}\nProvide feedback on correctness, errors, and suggestions.")
                try:
                    feedback = openai.chat.completions.create(
                        model='gpt-4o',
                        messages=[{'role': 'user', 'content': prompt}],
                        temperature=0.6
                    )
                    feedback_text = feedback.choices[0].message.content
                    await websocket.send_text(feedback_text)
                    if selected_language not in chat_responses:
                        chat_responses[selected_language] = []
                    chat_responses[selected_language].append(feedback_text)
                except Exception as e:
                    print(f"OpenAI API error for code check: {e}")
                    await websocket.send_text("Error checking code. Please try again.")

        except json.JSONDecodeError:
            await websocket.send_text("Invalid input format.")
        except Exception as e:
            print(f"WebSocket error: {e}")
            break