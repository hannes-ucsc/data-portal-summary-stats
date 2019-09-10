terraform {
  required_version = ">=0.12"
}

provider "aws" {
  assume_role {
    role_arn = var.role_arn
  }
  region = var.region
}

data "aws_caller_identity" "current"{}
data "aws_region" "current" {}

//data "aws_vpc" "default" {
//  default = true
//}

data "aws_vpc" "data-portal-summary-stats" {
  id = var.dpss_vpc_id
}

//data "aws_iam_role" "ecs_task_execution_role" {
//  name = "ecsTaskExecutionRole"
//}

// Fetch AZs in current region.
data "aws_availability_zones" "available" {}

data "aws_subnet" "default" {
  vpc_id = "${data.aws_vpc.data-portal-summary-stats.id}"
  cidr_block = "10.0.1.0/24"
}

//data "aws_subnet" "default" {
//  count = 2
//  vpc_id = "${data.aws_vpc.default.id}"
//  availability_zone = "${data.aws_availability_zones.available.names[count.index]}"
//  default_for_az = true
//}

data "aws_ecs_cluster" "default"{
  cluster_name = var.app_name
}

locals {
  common_tags = "${map(
    "managedBy"       , "terraform",
    "environ"         , "dev",
    "source"          , "canned",
    "min_gene_count"  , "1200",
    "blacklist"       , "true"
  )}"
}

/*
In the following we first define an IAM role, then we create policies, and finally, we attach
those the policies to the roles.
*/

/*
Policy and role for ECS events
*/
resource "aws_iam_role" "data-portal-summary-stats_ecs_events" {
  name = "data-portal-summary-stats_ecs_events"
  description = "Run dpss ecs task"
  assume_role_policy = <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "",
      "Effect": "Allow",
      "Principal": {
        "Service": [
          "ecs.amazonaws.com",
          "ecs-tasks.amazonaws.com",
          "events.amazonaws.com"
        ]
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF
}

resource "aws_iam_policy" "data-portal-summary-stats_ecs_events-policy" {
  name = "data-portal-summary-stats-policy-run-task"
  description = "Run dpss ecs task"

  policy = <<DOC
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "ecs:RunTask"
            ],
            "Resource": [
                "*"
            ]
        },
        {
            "Effect": "Allow",
            "Action": [
                "iam:PassRole"
            ],
            "Resource": [
                "*"
            ],
            "Condition": {
                "StringLike": {
                    "iam:PassedToService": "ecs-tasks.amazonaws.com"
                }
            }
        }
    ]
}
DOC
}

// Connect role to policy.
resource "aws_iam_role_policy_attachment" "ecs_events_attach" {
  policy_arn = "${aws_iam_policy.data-portal-summary-stats_ecs_events-policy.arn}"
  role       = "${aws_iam_role.data-portal-summary-stats_ecs_events.id}"
}

resource "aws_iam_role_policy_attachment" "ecs_events_attach2" {
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
  role       = "${aws_iam_role.data-portal-summary-stats_ecs_events.id}"
}

/*
??
*/
resource "aws_iam_role" "data-portal-summary-stats-task-performer" {
  name = "data-portal-summary-stats-task-performer"
  tags = "${local.common_tags}"
  assume_role_policy = <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": [
          "ecs-tasks.amazonaws.com"
        ]
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF
}

resource "aws_iam_policy" "data-portal-summary-stats-task-performer-policy" {
  name = "data-portal-summary-stats-task-performer-policy"
  description = "Perform task"

  policy = <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "tag:GetTagKeys",
        "tag:GetResources",
        "tag:GetTagValues",
        "cloudwatch:*"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action":[
        "logs:FilterLogEvents",
        "logs:GetLogEvents",
        "logs:GetQueryResults",
        "logs:DescribeLogGroups",
        "logs:DescribeLogStreams",
        "logs:GetLogRecord",
        "logs:StartQuery",
        "logs:StopQuery"
      ],
      "Resource": "arn:aws:logs:*:*:*"
    },
    {
      "Effect": "Allow" ,
      "Action": [
        "ecs:CreateCluster",
        "ecs:DeregisterContainerInstance",
        "ecs:DiscoverPollEndpoint",
        "ecs:Poll",
        "ecs:RegisterContainerInstance",
        "ecs:StartTelemetrySession",
        "ecs:Submit*",
        "ecs:ListTasks"
      ],
      "Resource": "*"
    },
    {
      "Sid": "VisualEditor0",
      "Effect": "Allow",
      "Action": "s3:ListBucket",
      "Resource": "arn:aws:s3:::*"
    },
    {
      "Sid": "VisualEditor1",
      "Effect": "Allow",
      "Action": [
          "s3:PutObject",
          "s3:GetObject"
      ],
      "Resource": "arn:aws:s3:::*/*"
    }
  ]
}
EOF
}

resource "aws_iam_role_policy_attachment" "task-performer-attach" {
  policy_arn = "${aws_iam_policy.data-portal-summary-stats-task-performer-policy.arn}"
  role = "${aws_iam_role.data-portal-summary-stats-task-performer.id}"
}

resource "aws_ecs_task_definition" "dpss_ecs_task_definition" {
  family = "${var.app_name}-${var.deployment_stage}"
  execution_role_arn       = "${aws_iam_role.data-portal-summary-stats_ecs_events.arn}"
  task_role_arn            = "${aws_iam_role.data-portal-summary-stats-task-performer.arn}"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.dpss_task_cpu
  memory                   = var.dpss_task_memory
  tags                     = "${local.common_tags}"
  container_definitions    = <<DEFINITION
[
  {
    "family": "data-portal-summary-stats",
    "name": "data-portal-summary-stats-fargate",
    "image": "${var.ecr_path}${var.image_name}:${var.image_tag}",
    "essential": true,
    "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "${aws_cloudwatch_log_group.task-execution.name}",
          "awslogs-region": "${var.region}",
          "awslogs-stream-prefix": "ecs"
        }
    },
    "command": [
          "--environ",
          "dev",
          "--source",
          "canned",
          "--blacklist",
          "false",
          "--min_gene_count",
          "1200"
     ],
    "name": "${var.app_name}"
  }
]
DEFINITION
}

// To run ECS scheduled tasks we need to use CloudWatch event rules...
resource "aws_cloudwatch_event_rule" "dpss-scheduler" {
  name                = "dpss-trigger-${var.deployment_stage}"
  description         = "Schedule to run data-portal-summary-stats"
  tags                = "${local.common_tags}"
  schedule_expression = "rate(5 minutes)"
}

resource "aws_cloudwatch_event_target" "scheduled_task" {
  target_id = "run-scheduled-dpss-task-every-24h"
  arn = "${data.aws_ecs_cluster.default.arn}"
  rule = "${aws_cloudwatch_event_rule.dpss-scheduler.name}"
  role_arn = "${aws_iam_role.data-portal-summary-stats_ecs_events.arn}"

  ecs_target {
      task_count          = 1
      task_definition_arn = "${aws_ecs_task_definition.dpss_ecs_task_definition.arn}"
      launch_type         = "FARGATE"
      platform_version    = "LATEST"

      network_configuration {
        assign_public_ip  = true
        subnets           = "${data.aws_subnet.default.*.id}"
        security_groups = ["${var.dpss_security_group_id}"]
      }
    }
  input = <<DOC
{
  "containerOverrides": [
    {
      "command": [
        "--environ","dev",
        "--source","canned",
        "--blacklist","false",
        "--min_gene_count","300"
      ]
    }
  ]
}
DOC
}

resource "aws_cloudwatch_log_group" "task-execution" {
  name              = "/ecs/${var.app_name}-${var.deployment_stage}"
  retention_in_days = 1827  // that's 5 years
}