from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

# 初始化 FastAPI 应用
app = FastAPI(title="GLM-4-9b-Chat API", description="API for interacting with GLM-4-9b-Chat model")

# 检查 CUDA 是否可用，并设置设备
device = torch.device("cuda:1" if torch.cuda.is_available() else "cpu")
if device.type == "cpu":
    raise RuntimeError("CUDA device 1 is not available. Please check your GPU setup.")

# 加载模型和分词器
model_path = "/data/ASRProject/glm-4-9b-chat/"
tokenizer = AutoTokenizer.from_pretrained(model_path)
model = AutoModelForCausalLM.from_pretrained(model_path).to(device)

# 定义输入数据模型
class TextInput(BaseModel):
    prompt: str
    max_length: int = 100  # 默认生成的最大长度

# 定义 API 路由
@app.post("/generate/")
async def generate_text(input_data: TextInput):
    try:
        # 对输入文本进行编码
        inputs = tokenizer(input_data.prompt, return_tensors="pt").to(device)
        
        # 生成文本
        outputs = model.generate(
            **inputs,
            max_length=input_data.max_length,
            pad_token_id=tokenizer.eos_token_id
        )
        
        # 解码生成的文本
        generated_text = tokenizer.decode(outputs[0], skip_special_tokens=True)
        return {"generated_text": generated_text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8082)