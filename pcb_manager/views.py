import json
import base64
import traceback
import logging
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.exceptions import ParseError, APIException

from .models import Device, PCBAnalysisResult
from .serializers import (
    DeviceResponseSerializer, DeviceWithMessagesSerializer
)

from langchain_openai import ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import PromptTemplate

import environ

env = environ.Env()
environ.Env.read_env()

# Set up logging for debugging
logger = logging.getLogger(__name__)

# --- LLM Setup (can be moved to a separate file, e.g., api/llm.py) ---
api_key = env("GOOGLE_API_KEY")

if api_key:
    primary_llm = ChatGoogleGenerativeAI(model="gemini-1.5-flash", temperature=0.1, api_key=api_key)
    model_name = "gemini-1.5-flash"
else:
    primary_llm = ChatOpenAI(base_url="http://localhost:1234/v1", api_key="lm-studio")
    model_name = "lm-studio"

print(f"Using LLM: {model_name}")


class AIAnalysisException(APIException):
    status_code = 500
    default_detail = 'Error during AI analysis.'
    default_code = 'ai_error'

# --- API Views ---

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def analyze_and_save_device(request):
    """
    Analyzes a PCB image and saves the resulting device for the authenticated user.
    """
    image_file = request.FILES.get('image')
    if not image_file:
        raise ParseError("Image file not provided.")
    if not image_file.content_type.startswith("image/"):
        raise ParseError("Invalid file type. Please upload an image.")

    try:
        # Read image bytes and reset pointer
        image_bytes = image_file.read()
        image_base64 = base64.b64encode(image_bytes).decode("utf-8")
        image_file.seek(0)  # Reset for DRF serializer later
        
        prompt_template = """
        Analyze the provided image of a Printed Circuit Board (PCB). Based on your analysis, provide a detailed and structured JSON output.

        Identify the key characteristics of the board and follow these instructions:
        - complexity: Classify the board's complexity as 'Low', 'Medium', or 'High' based on component density, number of layers, and trace routing.
        - components: List the names of the most prominent and identifiable components on the board.
        - operating_voltage: Estimate the primary operating voltage (e.g., "3.3V", "5V", "12V", "3.3V - 5V"). If unsure, state "Not determinable".
        - description: Write a concise, one-paragraph technical description of the board's likely function and features.

        {format_instructions}

        The user has provided the image. Analyze it now.
        """

        # Create prompt
        parser = JsonOutputParser(pydantic_object=PCBAnalysisResult)
        prompt = PromptTemplate(
            template=prompt_template,
            input_variables=[],
            partial_variables={"format_instructions": parser.get_format_instructions()},
        )

        message_content = [
            {"type": "text", "text": prompt.format()},
            {"type": "image_url", "image_url": f"data:{image_file.content_type};base64,{image_base64}"}
        ]
        if not model_name.startswith("gemini"):
            message_content[1]["image_url"] = {"url": message_content[1]["image_url"]}

        message = HumanMessage(content=message_content)
        output = primary_llm.invoke([message])

        if not output.content:
            raise AIAnalysisException(detail="LLM returned empty response")

        content = output.content.strip()
        if content.startswith("```json"):
            content = content[7:]
        if content.endswith("```"):
            content = content[:-3]

        try:
            parsed_data = json.loads(content)
        except json.JSONDecodeError:
            raise AIAnalysisException(detail="LLM output is not valid JSON.")

        try:
            analysis = parser.parse(content)
        except Exception:
            analysis = parsed_data

        # Add fallback/default name (could be user-generated later)
        device_data = {
            "name": request.data.get("name", "AI-Analyzed Device"),  # Allow custom name
            "components": analysis.get("components", []),
            "operating_voltage": analysis.get("operating_voltage"),
            "complexity": analysis.get("complexity"),
            "description": analysis.get("description"),
            "image": image_file,
        }

        serializer = DeviceResponseSerializer(data=device_data)
        if serializer.is_valid():
            serializer.save(user=request.user)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    except AIAnalysisException as e:
        raise e
    except Exception as e:
        logger.error(traceback.format_exc())
        raise AIAnalysisException(detail=f"Unexpected error: {str(e)}")


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_all_devices(request):
    """
    Retrieve all devices for the authenticated user.
    """
    devices = Device.objects.filter(user=request.user).order_by('-created_at')
    serializer = DeviceResponseSerializer(devices, many=True)
    # print(serializer.data)  # Debugging output
    return Response(serializer.data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_device_by_id(request, device_id):
    """
    Retrieve a specific device by its ID for the authenticated user, including its chat history.
    """
    device = get_object_or_404(Device, pk=device_id, user=request.user)
    serializer = DeviceWithMessagesSerializer(device)
    return Response(serializer.data)


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_device(request, device_id):
    """
    Delete a specific device by its ID for the authenticated user.
    """
    device = get_object_or_404(Device, pk=device_id, user=request.user)
    device.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def chat_with_device(request, device_id):
    """
    Persistent chat endpoint for user's device. Django's ORM handles database sessions.
    """
    device = get_object_or_404(Device, pk=device_id, user=request.user)
    user_message_content = request.data.get('message')
    if not user_message_content:
        raise ParseError("Message content not provided.")

    # --- Step 1: Save user message and get history ---
    device.chat_messages.create(role="user", content=user_message_content)
    history_from_db = device.chat_messages.all().order_by('created_at')

    # --- Step 2: AI Processing ---
    try:
        components_str = ", ".join(device.components)
        device_context = f"""
        Device Information:
        - Name: {device.name}
        - Owner: {device.user.username}
        - Complexity: {device.complexity}
        - Components: {components_str}
        - Operating Voltage: {device.operating_voltage}
        - Description: {device.description}
        - Image: Available at {request.build_absolute_uri(device.image.url)}
        """
        system_message = SystemMessage(content=f"You are an expert electronics engineer specializing in PCB analysis and troubleshooting. {device_context}")

        conversation_history = [system_message]
        for msg in history_from_db:
            if msg.role == "user":
                conversation_history.append(HumanMessage(content=msg.content))
            elif msg.role == "ai":
                conversation_history.append(AIMessage(content=msg.content))

        response = primary_llm.invoke(conversation_history)
        ai_response_content = response.content
        
        if not ai_response_content:
            raise AIAnalysisException(detail="AI returned empty response")

    except Exception as e:
        logger.error(f"Error in chat_with_device: {str(e)}")
        logger.error(traceback.format_exc())
        raise AIAnalysisException(detail=f"Error during AI processing: {str(e)}")

    # --- Step 3: Save AI Response to Database ---
    device.chat_messages.create(role="ai", content=ai_response_content)

    return Response({
        "device_id": device.id,
        "ai_response": ai_response_content,
    }, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_user_stats(request):
    """
    Get statistics for the authenticated user.
    """
    user_devices = Device.objects.filter(user=request.user)
    total_devices = user_devices.count()
    total_messages = sum(device.chat_messages.count() for device in user_devices)
    
    return Response({
        "username": request.user.username,
        "total_devices": total_devices,
        "total_chat_messages": total_messages,
        "devices_by_complexity": {
            "Low": user_devices.filter(complexity="Low").count(),
            "Medium": user_devices.filter(complexity="Medium").count(),
            "High": user_devices.filter(complexity="High").count(),
        }
    })


# Debug endpoint to test LLM connection
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def test_llm_connection(request):
    """
    Test endpoint to verify LLM connectivity for authenticated users.
    """
    try:
        test_message = HumanMessage(content="Respond with a simple JSON object: {\"status\": \"working\", \"message\": \"LLM is functioning correctly\"}")
        response = primary_llm.invoke([test_message])
        
        return Response({
            "user": request.user.username,
            "llm_model": model_name,
            "connection_status": "success",
            "response_type": type(response).__name__,
            "response_content": response.content,
            "has_content": bool(response.content)
        })
    except Exception as e:
        return Response({
            "user": request.user.username,
            "llm_model": model_name,
            "connection_status": "failed",
            "error": str(e),
            "traceback": traceback.format_exc()
        }, status=500)