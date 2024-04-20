terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 4.16"
    }
  }

  required_version = ">= 1.2.0"
}

provider "aws" {
  region = "us-east-2"
}

resource "null_resource" "pip_install_discord_openai" {
  triggers = {
    shell_hash = "${sha256(file("${path.module}/python_reqs.txt"))}"
  }

  provisioner "local-exec" {
    command = "pip install -r python_reqs.txt -t ${path.module}/layers/discord_openai_layer --upgrade"
  }
}