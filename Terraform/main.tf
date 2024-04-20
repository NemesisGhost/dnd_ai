terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 4.16"
    }
  }

  required_version = ">= 1.2.0"
}

variable "aws_access_key" {
  type = string
  description = "AWS Access Key"
}

variable "aws_secret_key" {
  type = string
  description = "AWS Secret Key"
}

provider "aws" {
  region = "us-east-2"
  access_key = var.aws_access_key
  secret_key = var.aws_secret_key
}

resource "null_resource" "pip_install_discord_openai" {
  triggers = {
    shell_hash = "${sha256(file("${path.module}/python_reqs.txt"))}"
  }

  provisioner "local-exec" {
    command = "pip install -r python_reqs.txt -t ${path.module}/layers/discord_openai_layer/python --upgrade --platform manylinux2014_x86_64 --only-binary=:all:"
  }
}