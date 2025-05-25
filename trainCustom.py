from donut.dataset import load_tickets_dataset
from donut.donut.model import DonutModel
from transformers import VisionEncoderDecoderTrainer, VisionEncoderDecoderTrainingArguments
from donut.donut.util import save_model
from transformers import DonutProcessor
import os

model = DonutModel.from_pretrained("naver-clova-ix/donut-base")
processor = DonutProcessor.from_pretrained("naver-clova-ix/donut-base")

dataset_path = "tickets"  # relativo a tu raíz
TicketDataset = load_tickets_dataset(processor, dataset_path)
train_dataset = TicketDataset(split="train")
val_dataset = TicketDataset(split="val")

args = VisionEncoderDecoderTrainingArguments(
    output_dir="./donut/finetuned",
    per_device_train_batch_size=2,
    per_device_eval_batch_size=2,
    num_train_epochs=10,
    logging_steps=10,
    save_steps=100,
    evaluation_strategy="steps",
    save_total_limit=2,
    fp16=False,
    remove_unused_columns=False,
    learning_rate=5e-5,
    predict_with_generate=True,
)

trainer = VisionEncoderDecoderTrainer(
    model=model,
    args=args,
    train_dataset=train_dataset,
    eval_dataset=val_dataset,
    tokenizer=processor.tokenizer,
    data_collator=lambda data: {
        'pixel_values': torch.stack([f["pixel_values"] for f in data]),
        'labels': torch.stack([f["labels"] for f in data])
    }
)

trainer.train()
