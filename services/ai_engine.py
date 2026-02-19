
import os
from dotenv import load_dotenv
from typing import Optional

from pydantic import BaseModel, Field
from langchain_groq import ChatGroq
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import JsonOutputParser
import json
import re


load_dotenv()

def extract_json(text):
    try:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
    except Exception as e:
        print("JSON Parse Error:", e)
    return None


class FeedbackSchema(BaseModel):
    grammar_score: int = Field(description="Score from 0 to 10")
    confidence_score: int = Field(description="Score from 0 to 10")
    technical_depth_score: Optional[int] = Field(
        default=None,
        description="Score from 0 to 10 if technical interview"
    )
    improved_answer: str = Field(description="Improved professional answer")



parser = JsonOutputParser(pydantic_object=FeedbackSchema)



model = ChatGroq(
    model="llama-3.1-8b-instant",
    temperature=0.2,
    max_tokens=500,
    max_retries=2
)



def generate_feedback(answer: str, interview_type="hr", advanced=False):

    format_instructions = parser.get_format_instructions()

    if advanced:
        template = """
You are an expert interview evaluator.

Evaluate the answer professionally.

Return structured JSON.

{format_instructions}

Answer:
{answer}
"""
    else:
        template = """
Evaluate this HR interview answer professionally.

Return structured JSON.

{format_instructions}

Answer:
{answer}
"""

    prompt = PromptTemplate(
        template=template,
        input_variables=["answer"],
        partial_variables={"format_instructions": format_instructions},
    )

    chain = prompt | model | parser

    try:
        result = chain.invoke({"answer": answer})
        return result

    except Exception as e:
        print("LLM ERROR:", e)


        return FeedbackSchema(
            grammar_score=5,
            confidence_score=5,
            technical_depth_score=5 if advanced else None,
            improved_answer="Could not generate improved answer."
        ).dict()