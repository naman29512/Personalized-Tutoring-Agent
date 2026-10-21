import chromadb
import sys
import time
import urllib.request
import urllib.error
import json

DB_DIR = "chroma_db"
API_KEY = "API key here"
URL_FLASH = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent?key={API_KEY}"

def db(user_question, result=2):
    """checks the vector db"""
    client = chromadb.PersistentClient(path=DB_DIR)
    collection = client.get_collection(name="mit_course_data")

    results = collection.query(
        query_texts=[user_question], 
        n_results=result
    )
    return results

def get_available_materials():
    """Extracts unique source filenames from ChromaDB metadata."""
    client = chromadb.PersistentClient(path=DB_DIR)
    collection = client.get_collection(name="mit_course_data")
    data = collection.get(include=["metadatas"])
    
    sources = set()
    for meta in data.get("metadatas", []):
        if meta and "source" in meta:
            sources.add(meta["source"])
            
    return sorted(list(sources))

def agent(url, prompt, prev_convo=None, system_prompt=None, json_mode=False, schema=None, max_retries=6):
    """sends the prompt to gemini and recieves its response"""
    if prev_convo is None:
        prev_convo = []
        
    new_message = {"role": "user", "parts": [{"text": prompt}]} # message format
    current_convo = prev_convo + [new_message]
    send = {"contents": current_convo}
    
    # Injects system rules separately from chat history
    if system_prompt:
        send["systemInstruction"] = {"parts": [{"text": system_prompt}]}
        
    # Forces raw JSON output when generating structured quizzes
    if json_mode:
        send["generationConfig"] = {"responseMimeType": "application/json"}
        if schema:
            send["generationConfig"]["responseSchema"] = schema
    
    data = json.dumps(send).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"}
    )
    
    base_delay = 2
    
    for attempt in range(max_retries): 
        try: 
            with urllib.request.urlopen(req) as response:
                result = json.loads(response.read().decode("utf-8"))
                
                # Check for safety filter blocks or empty responses
                candidate = result.get("candidates", [{}])[0]
                parts = candidate.get("content", {}).get("parts", [{}])
                if not parts or "text" not in parts[0]:
                    finish_reason = candidate.get("finishReason", "UNKNOWN")
                    raise ValueError(f"No response text returned. Finish reason: {finish_reason}")
                
                reply = parts[0]["text"]
                return reply
                
        except urllib.error.HTTPError as e:
            error_body = e.read().decode('utf-8')
            
            # Checks for hard quota limit (do not retry)
            if "limit: 20" in error_body or "GenerateRequestsPerDay" in error_body:
                print(error_body)
                print("\n[FATAL] Daily quota exhausted.")
                sys.exit(1)
                
            # Check for throttle/busy errors (retry these)
            if e.code in [429, 503] or any(k in error_body for k in ["UNAVAILABLE", "RESOURCE_EXHAUSTED", "Overloaded"]):
                if attempt < max_retries - 1:
                    sleep_time = base_delay * (2 ** attempt)
                    print(f"\n[!] API Busy/Throttled. Retrying in {sleep_time}s... (Attempt {attempt + 1}/{max_retries})")
                    time.sleep(sleep_time)
                    print(f"HTTP Error {e.code}: {error_body}")
                else:
                    print("\n[FATAL] Max retries reached.")
                    sys.exit(1)
            else:
                # If it's a 400 Bad Request or something else, crash so you can see the error
                raise Exception(f"HTTP Error {e.code}: {error_body}")
                
        except Exception as e:
            # Catch standard network connection drops
            if attempt < max_retries - 1:
                sleep_time = base_delay * (2 ** attempt)
                print(f"\n[!] Network Error ({e}). Retrying in {sleep_time}s... (Attempt {attempt + 1}/{max_retries})")
                time.sleep(sleep_time)
            else:
                raise e

def learn(user_input, chat_history, url=URL_FLASH, max_score=1.2):
    data = db(user_input, 3)
    if data["distances"][0][0] >= max_score:
        return "the specific topic/query doesnt exist in the material provided"

    # Pair the text documents and metadata together, then format them with source names
    formatted_chunks = []
    for doc, meta in zip(data["documents"][0], data["metadatas"][0]):
        source_name = meta.get("source", "Unknown Source")
        formatted_chunk = f"--- Source File: {source_name} ---\n{doc}"
        formatted_chunks.append(formatted_chunk)
        
    context_string = "\n\n".join(formatted_chunks)

    system_prompt = f"""
    You are an expert Teacher AI. Your goal is to deeply explain the user's query using the provided Source Context as your factual foundation. Do not just copy-paste the text—act like a world-class tutor and break the concepts down.

    RULES:
    1. FACTUAL GROUNDING: Every core claim, definition, or fact must come from the Source Context and include its source title and location.
    2. PEDAGOGICAL FREEDOM: You are ENCOURAGED to use analogies, simple examples, and step-by-step breakdowns from your own knowledge to explain the facts found in the text. (e.g., If the text says "Python is object-oriented", explain what that actually means).
    3. For video transcripts, write: "As stated in [Cleaned Video Title] at timestamp [MM:SS]...".
    4. For PDF documents, write: "According to [Cleaned PDF Title] on page X...".
    5. Never output raw filenames (like `lecture-1.md`). Translate them into professional titles.
    6. Design ONE open-ended check-for-understanding question based on the explanation, and assign it a weightage (1 for basic recall, 2 for conceptual application, 3 for deep critical analysis).
    7. Generate 2 to 3 logical follow-up topics to dive deep into that naturally follow up this explanation.

    Source Context:
    {context_string}
    """
    learn_schema = {
        "type": "OBJECT",
        "properties": {
            "explanation": {
                "type": "STRING",
                "description": "The detailed, grounded teaching explanation with professional citations woven in."
            },
            "deep_dive_topics": {
                "type": "ARRAY",
                "description": "A list of 2 to 3 specific sub-topics or logical next steps to explore. Example: ['Variables', 'Functions', 'Classes']",
                "items": {
                    "type": "STRING"
                }
            },
            "check_question": {
                "type": "OBJECT",
                "properties": {
                    "question_text": {
                        "type": "STRING",
                        "description": "A single open-ended question to test the student's understanding of the explanation."
                    },
                    "ideal_answer": {
                        "type": "STRING",
                        "description": "The correct, detailed explanation or answer to the question."
                    },
                    "weightage": {
                        "type": "INTEGER",
                        "description": "The difficulty/weight of the check question: integer 1 (Easy), 2 (Medium), 3 (Hard)."
                    }
                },
                "required": ["question_text", "ideal_answer", "weightage"]
            }
        },
        "required": ["explanation", "check_question"]
    }
    reply = agent(
        url=URL_FLASH,
        prompt=user_input,
        prev_convo=chat_history,
        system_prompt=system_prompt,
        json_mode=True,  
        schema=learn_schema
    )
    
    return reply

def quiz(selected_materials: list, mastery_profile: dict, url=URL_FLASH):
    """
    Generates a quiz scoped to specific study materials (e.g., Lecture PDFs/Videos).
    Biases question generation toward the student's weakest topics.
    """
    client = chromadb.PersistentClient(path=DB_DIR)
    collection = client.get_collection(name="mit_course_data")
    
    all_chunks = []
    import random
    
    # 1. Filter ChromaDB by EXACT filename/source instead of vector similarity
    for material in selected_materials:
        data = collection.get(where={"source": material}, include=["documents"])
        if data and data.get("documents"):
            # Sample up to 15 chunks per material to avoid token limits while getting broad coverage
            docs = data["documents"]
            sample_size = min(15, len(docs))
            sampled_docs = random.sample(docs, sample_size)
            for doc in sampled_docs:
                all_chunks.append(f"--- Source: {material} ---\n{doc}")

    context_string = "\n\n".join(all_chunks) if all_chunks else "General course material."

    # 2. Feed the student's exact BKT scores to the AI so it targets their weaknesses
    system_prompt = f"""
    You are an expert Course Examiner AI. Generate a diagnostic assessment (MCQ and Subjective).
    
    STUDENT MASTERY PROFILE (Lower score = Weaker):
    {json.dumps(mastery_profile, indent=2)}
    
    RULES:
    1. Scope: Only test concepts found in the provided Source Context.
    2. Adaptive: Analyze the Student Mastery Profile. Heavily bias the generated questions toward the student's weakest concepts. 
    3. Tagging: Assign a clear, atomic 'topic' string to each question so the tracking algorithm can evaluate it.
    
    Source Context:
    {context_string}
    """

# Update the schema inside quiz() to include 'explanation'
    quiz_schema = {
        "type": "OBJECT",
        "properties": {
            "questions": {
                "type": "ARRAY",
                "items": {
                    "type": "OBJECT",
                    "properties": {
                        "question_text": {"type": "STRING"},
                        "type": {"type": "INTEGER", "description": "0 for MCQ, 1 for Subjective."},
                        "weightage": {"type": "INTEGER", "description": "Difficulty: integer 1, 2, or 3."},
                        "topic": {"type": "STRING", "description": "The specific atomic topic this question tests."},
                        "options": {"type": "ARRAY", "items": {"type": "STRING"}},
                        "correct_answer": {"type": "STRING", "description": "The exact correct option (MCQ) or ideal reference solution (Subjective)."},
                        "explanation": {"type": "STRING", "description": "A detailed explanation of the concept and why the answer is correct."}
                    },
                    "required": ["question_text", "type", "weightage", "topic", "options", "correct_answer", "explanation"]
                }
            }
        },
        "required": ["questions"]
    }

    reply = agent(
        url=url, 
        prompt=f"Generate an adaptive quiz covering these materials: {selected_materials}", 
        system_prompt=system_prompt, 
        json_mode=True, 
        schema=quiz_schema
    )
    
    result = json.loads(reply)
    formatted_quiz = []
    for q in result.get("questions", []):
        formatted_quiz.append([
            q.get("question_text"),
            q.get("type"),
            q.get("weightage"),
            q.get("topic"),
            q.get("options", []),
            q.get("correct_answer"),
            q.get("explanation", "No explanation provided.") # Grab the new explanation
        ])

    return formatted_quiz

def grade(submission_data: list, url=URL_FLASH) -> list:
    """
    Grades a batch of answers in a single AI call.
    
    Parameters:
        submission_data: 2D list where each item is 
                         [question, student_answer, type, weightage, topic, correct_solution_key]
                         type: 0 for MCQ, 1 for Subjective
                         
    Returns:
        2D list of results formatted as [final_marks, explanation] for each question.
    """
    if not submission_data:
        return []

    formatted_items = []
    for idx, item in enumerate(submission_data):
        ques, ans, q_type, weight, topic, sol = item[0], item[1], item[2], item[3], item[4], item[5]
        type_str = "MCQ / Objective (0)" if q_type == 0 else "Subjective / Conceptual (1)"
        
        formatted_items.append(
            f"--- Item Index {idx} ---\n"
            f"Topic: {topic}\n"
            f"Question Type: {type_str}\n"
            f"Question: {ques}\n"
            f"Reference Solution / Correct Answer: {sol}\n"
            f"Student Answer: {ans}\n"
            f"Max Weightage: {weight}"
        )

    batch_prompt = "\n\n".join(formatted_items)

    system_prompt = """
    You are an academic evaluator. Grade all student answers based on the provided reference solutions and topics.
    
    RULES:
    1. For Type 0 (MCQ): Binary check. If the student answer matches the correct solution, award full marks (Max Weightage). Otherwise, award 0.
    2. For Type 1 (Subjective): Evaluate conceptual accuracy against the reference solution. Award marks between 0 and Max Weightage (partial credit allowed).
    3. Provide a concise explanation/feedback sentence for why the marks were awarded.
    """

    grading_schema = {
        "type": "OBJECT",
        "properties": {
            "evaluations": {
                "type": "ARRAY",
                "items": {
                    "type": "OBJECT",
                    "properties": {
                        "index": {"type": "INTEGER", "description": "The 0-based index of the question."},
                        "marks_awarded": {"type": "INTEGER", "description": "Marks earned, between 0 and Max Weightage."},
                        "explanation": {"type": "STRING", "description": "Short explanation or grading feedback."}
                    },
                    "required": ["index", "marks_awarded", "explanation"]
                }
            }
        },
        "required": ["evaluations"]
    }

    reply = agent(
        url=url,
        prompt=batch_prompt,
        system_prompt=system_prompt,
        json_mode=True,
        schema=grading_schema
    )

    result = json.loads(reply)
    evals = result.get("evaluations", [])

    # Pre-fill with default failsafes matching input length
    final_results = [[0, "Evaluation failed."] for _ in range(len(submission_data))]

    for entry in evals:
        idx = entry.get("index")
        awarded = entry.get("marks_awarded", 0)
        explanation = entry.get("explanation", "No explanation provided.")
        
        if 0 <= idx < len(submission_data):
            max_weight = submission_data[idx][3]
            clamped_marks = max(0, min(max_weight, awarded))
            final_results[idx] = [clamped_marks, explanation]

    return final_results