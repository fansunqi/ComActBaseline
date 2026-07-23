import json
import logging
import re
from datetime import datetime
from typing import Dict, List, Tuple
import base64
import tiktoken
import requests
import xml.etree.ElementTree as ET
import time

from prompts_comcad import system_prompt, sldworks_3d_model_example, inventor_3d_model_example, autocad_2d_sketch_example, \
    inventor_assembly_example, sldworks_drawing_example, sldworks_mass_property_example, inventor_mass_property_example, \
    sldworks_interference_example, inventor_interference_example, sldworks_modify_example, inventor_modify_example, \
    build_user_message, build_user_message_with_rag

logger = logging.getLogger("myexp.agent")

def resize_image_openai(image):
    """
    Resize the image to OpenAI's input resolution so that text written on it doesn't get processed any further.

    Steps:
    1. If the image's largest side is greater than 2048, scale it down so that the largest side is 2048, maintaining aspect ratio.
    2. If the shortest side of the image is longer than 768px, scale it so that the shortest side is 768px.
    3. Return the resized image.

    Reference: https://platform.openai.com/docs/guides/vision/calculating-costs
    """
    # max_size = 2048 # max_size应该是2000
    max_size = 2000
    target_short_side = 768

    out_w, out_h = image.size

    # Step 0: return the image without scaling if it's already within the target resolution
    if out_w <= max_size and out_h <= max_size and min(out_w, out_h) <= target_short_side:
        return image, out_w, out_h, 1.0

    # Initialize scale_factor
    scale_factor = 1.0

    # Step 1: Calculate new size to fit within a 2048 x 2048 square
    max_dim = max(out_w, out_h)
    if max_dim > max_size:
        scale_factor = max_size / max_dim
        out_w = int(out_w * scale_factor)
        out_h = int(out_h * scale_factor)

    # Step 2: Calculate new size if the shortest side is longer than 768px
    min_dim = min(out_w, out_h)
    if min_dim > target_short_side:
        new_scale_factor = target_short_side / min_dim
        out_w = int(out_w * new_scale_factor)
        out_h = int(out_h * new_scale_factor)
        # Combine scale factors from both steps
        scale_factor *= new_scale_factor

    # Perform the resize operation once
    resized_image = image.resize((out_w, out_h))

    return resized_image, out_w, out_h, scale_factor  # 缩放因子用于坐标映射，这个意思是不是所有送进去的screenshot都被缩放了，那怎么看screenshot的分辨率对agent的影响呢

# Function to encode the image
def encode_image(image_content):
    return base64.b64encode(image_content).decode('utf-8')

class PromptAgent:
    def __init__(
            self,
            model='gpt-4o',
            temperature=1.0,
            top_p=0.9,
            max_tokens=5000,
            max_steps=3,
            max_trajectory_length=2,
            api_server='claudeshop',
            base_url="",
            api_key="",

            with_example=False,
            task_type='3d_model',
            software='sldworks',

            with_rag = False
    ):
        self.model = model
        self.temperature = temperature
        self.top_p = top_p
        self.max_tokens = max_tokens

        self.api_server = api_server
        self.base_url = base_url
        self.api_key = api_key

        self.max_steps = max_steps,
        self.max_trajectory_length = max_trajectory_length

        self.past_thoughts = []
        self.past_actions = []
        self.past_observations = []

        if not with_example:
            self.system_message = system_prompt
        elif task_type == '3d_model':
            if software == 'sldworks':
                self.system_message = system_prompt + sldworks_3d_model_example
            elif software == 'inventor':
                self.system_message = system_prompt + inventor_3d_model_example
            else:
                logger.error(f"Invalid software!!! {software}")
        elif task_type == '2d_sketch':
            if software == 'autocad':
                self.system_message = system_prompt + autocad_2d_sketch_example
            else:
                logger.error(f"Invalid software!!! {software}")
        elif task_type == 'assembly':
            if software == 'inventor':
                self.system_message = system_prompt + inventor_assembly_example
            else:
                logger.error(f"Invalid software!!! {software}")
        elif task_type == 'modify':
            if software == 'sldworks':
                self.system_message = system_prompt + sldworks_modify_example
            elif software == 'inventor':
                self.system_message = system_prompt + inventor_modify_example
            else:
                logger.error(f"Invalid software!!! {software}")
        elif task_type == 'drawing':
            if software == 'sldworks':
                self.system_message = system_prompt + sldworks_drawing_example
            else:
                logger.error(f"Invalid software!!! {software}")
        elif task_type == 'mass_property':
            if software == 'sldworks':
                self.system_message = system_prompt + sldworks_mass_property_example
            elif software == 'inventor':
                self.system_message = system_prompt + inventor_mass_property_example
            else:
                logger.error(f"Invalid software!!! {software}")
        elif task_type == 'interference_detection':
            if software == 'sldworks':
                self.system_message = system_prompt + sldworks_interference_example
            elif software == 'inventor':
                self.system_message = system_prompt + inventor_interference_example
            else:
                logger.error(f"Invalid software!!! {software}")
        elif task_type == '3d_model+drawing':
            if software == 'sldworks':
                self.system_message = system_prompt + sldworks_3d_model_example + sldworks_drawing_example
            else:
                logger.error(f"Invalid software!!! {software}")
        elif task_type == '3d_model+mass_property':
            if software == 'sldworks':
                self.system_message = system_prompt + sldworks_3d_model_example + sldworks_mass_property_example
            elif software == 'inventor':
                self.system_message = system_prompt + inventor_3d_model_example + inventor_mass_property_example
            else:
                logger.error(f"Invalid software!!! {software}")
        elif task_type == 'assembly+interference_detection':
            if software == 'inventor':
                self.system_message = system_prompt + inventor_assembly_example + inventor_interference_example
            else:
                logger.error(f"Invalid software!!! {software}")
        elif task_type == '3d_model+modify':
            if software == 'sldworks':
                self.system_message = system_prompt + sldworks_3d_model_example + sldworks_modify_example
            elif software == 'inventor':
                self.system_message = system_prompt + inventor_3d_model_example + inventor_modify_example
            else:
                logger.error(f"Invalid software!!! {software}")
        else:
            logger.error(f"Invalid task type!!! {task_type}")

        self.with_rag = with_rag

    def predict(self, instruction: str, obs: Dict, api_list: List):
        system_message = self.system_message

        # prompt patch for claude
        if 'claude' in self.model:
            system_message = system_message+"""IMPORTANT NOTES:
1. Your response must contain exactly ONE decision block and, if the decision is CODE, exactly ONE ```python``` block containing the entire script. Do NOT split your code across multiple blocks.
2. Keep your <thinking>...</thinking> reasoning as brief as possible. NO code blocks are allowed inside the thinking section.
"""

        messages = []
        if self.with_rag:
            system_message = system_message+f"""
Here are some COM APIs that might be useful for completing this task.
{api_list}"""

        messages.append({
            "role": "system",
            "content": [
                {
                    "type": "text",
                    "text": system_message
                },
            ]
        })
        messages.append({
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": f"- Task Instruction: {instruction}"
                }
            ]
        })
        
        assert len(self.past_observations) == len(self.past_actions) == len(self.past_thoughts), logger.error("The number of observations, actions and thoughts should be the same!")
        if len(self.past_observations) > self.max_trajectory_length:
            if self.max_trajectory_length == 0:
                _observations = []
                _actions = []
                _thoughts = []
            else:
                _observations = self.past_observations[-self.max_trajectory_length:]
                _actions = self.past_actions[-self.max_trajectory_length:]
                _thoughts = self.past_thoughts[-self.max_trajectory_length:]
        else:
            _observations = self.past_observations
            _actions = self.past_actions
            _thoughts = self.past_thoughts

        for previous_obs, previous_action, previous_thought in zip(_observations, _actions, _thoughts):
            _screenshot = previous_obs['screenshot']
            _terminal = previous_obs['terminal']
            messages.append({
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": build_user_message(_terminal)
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{_screenshot}",
                            "detail": "high"
                        }
                    }
                ]
            })

            messages.append({
                "role": "assistant",
                "content": previous_thought.strip() if len(previous_thought) > 0 else "No valid codes"
            })


        base64_image = encode_image(obs["screenshot"])
        self.past_observations.append({
            "screenshot": base64_image,
            "terminal": obs['terminal'],
        })

        messages.append({
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": build_user_message(obs['terminal'])
                },
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/png;base64,{base64_image}",
                        "detail": "high"
                    }
                }
            ]
        })

        logger.info(
            f'Call api arguments: model: {self.model}, max_tokens: {self.max_tokens}, top_p: {self.top_p}, temperature: {self.temperature}')
        try:
            start_call_llm_time = datetime.now()
            if self.api_server == 'claudeshop':
                if 'qwen3.5' in self.model.lower():
                    response = self.call_llm_claudeshop(
                        payload={
                            "model": self.model,
                            "messages": messages,
                            "max_tokens": self.max_tokens,
                            "top_p": self.top_p,
                            "temperature": self.temperature,
                            "chat_template_kwargs": {"enable_thinking": False}

                        },
                        base_url=self.base_url,
                        api_key=self.api_key,
                    )
                elif 'claude' in self.model.lower():
                    response = self.call_llm_claudeshop(
                        payload={
                            "model": self.model,
                            "messages": messages,
                            "max_tokens": self.max_tokens,
                        },
                        base_url=self.base_url,
                        api_key=self.api_key,
                    )
                elif 'glm-4.6v' in self.model.lower():
                    response = self.call_llm_claudeshop(
                        payload={
                            "model": self.model,
                            "messages": messages,
                            "max_tokens": self.max_tokens,
                            "temperature": self.temperature,
                        },
                        base_url=self.base_url,
                        api_key=self.api_key,
                    )
                else:
                    response = self.call_llm_claudeshop(
                        payload={
                            "model": self.model,
                            "messages": messages,
                            "max_tokens": self.max_tokens,
                            "top_p": self.top_p,
                            "temperature": self.temperature
                        },
                        base_url=self.base_url,
                        api_key=self.api_key
                    )


            elif self.api_server == 'azure':
                response = self.call_llm_sii(
                    model=self.model,
                    messages=messages,
                    max_tokens=self.max_tokens,
                    top_p=self.top_p,
                    temperature=self.temperature,
                    api_key=self.api_key
                )
            end_call_llm_time = datetime.now()
        except Exception as e:
            logger.error("Failed to call" + self.model + ", Error: " + str(e))
            raise RuntimeError(f"Failed to call {self.model}: {e}") from e

        py_codes = self.parse_py_codes(response['message']) if self.parse_py_codes(response['message']) else ""
        decision = self.parse_decision(response['message']) if self.parse_decision(response['message']) else "CODE"
        logger.info(f'===Decision: {decision}===')

        if (not py_codes) and ('CODE' in decision.upper()):
            logger.error("Failed to parse codes from response!")

        self.past_actions.append({
            "py_codes": py_codes,
            "decision": decision
        })
        self.past_thoughts.append(response['message'])

        # return response, py_codes, messages, (end_call_llm_time - start_call_llm_time).total_seconds()
        return response, py_codes, decision, messages, (end_call_llm_time - start_call_llm_time).total_seconds()

    def call_llm_claudeshop(self, payload, base_url, api_key):
        proxies = {}

        logger.info('In call_llm_claudeshop')

        is_glm_46v = 'glm-4.6v' in str(payload.get("model", "")).lower()
        request_timeout = 600 if is_glm_46v else 180
        payload = json.dumps(payload)

        url = base_url + "/v1/chat/completions"
        headers = {
            'Accept': 'application/json',
            'Authorization': f'Bearer {api_key}',
            'User-Agent': 'Apifox/1.0.0 (https://apifox.com)',
            'Content-Type': 'application/json'
        }

        attempt_count = 0
        max_attempts = 3 if is_glm_46v else 5
        while attempt_count < max_attempts:
            try:
                if 'https' in url:
                    logger.info(f'url: {url}, proxies: {proxies}')
                    response = requests.post(
                        url,
                        headers=headers,
                        data=payload,
                        proxies=proxies,
                        timeout=request_timeout,
                    )
                else:
                    logger.info(f'url: {url}')
                    response = requests.post(
                        url,
                        headers=headers,
                        data=payload,
                        timeout=request_timeout,
                    )

                if response.status_code == 200:
                    data = response.json()

                    if data['choices'][0]['message']['content'].strip():
                        processed_response = {
                            'message': data['choices'][0]['message']['content'],
                            'reasoning_content': data['choices'][0]['message'].get(
                                'reasoning_content'
                            ),
                            'model': data['model'],
                            'completion_tokens': data['usage']['completion_tokens'],
                            'prompt_tokens': data['usage']['prompt_tokens'],
                            'total_tokens': data['usage']['total_tokens'],
                            'raw_response': data,
                        }
                        logger.info(
                            "Processed response: model=%s, prompt_tokens=%s, "
                            "completion_tokens=%s",
                            processed_response["model"],
                            processed_response["prompt_tokens"],
                            processed_response["completion_tokens"],
                        )
                        return processed_response

                        exit(0)
                    else:
                        attempt_count += 1
                else:
                    logger.info(response.json())
                    attempt_count += 1
            except Exception as e:
                attempt_count += 1
                logger.error(f"Error occurred when calling openai api {e}, retrying...")
                time.sleep(5)
        raise RuntimeError(
            f"LLM API did not return a usable response after {max_attempts} attempts."
        )

    def parse_py_codes(self, response: str):
        matches = re.findall(r'```python\s*(.*?)\s*```', response, re.DOTALL)
        if matches:
            return matches[-1].strip()
        else:
            return None
    
    def parse_decision(self, response: str):
        matches = re.findall(r'```decision\s*(.*?)\s*```', response, re.DOTALL)
        if matches:
            return matches[-1].strip()
        else:
            return None

    def reset(self):
        self.past_thoughts = []
        self.past_actions = []
        self.past_observations = []
