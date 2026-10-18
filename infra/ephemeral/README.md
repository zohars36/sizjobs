# infra/ephemeral

Terraform for the AWS resources that are destroyed every evening and rebuilt
every morning (Part B only).

Examples: the EC2 instance running k3s, its security group and Elastic IP
association.

- Every resource is tagged `project=sizjobs` and `layer=ephemeral`.
- Reads outputs from `infra/persistent`; never owns data that must survive.
- Cost first: no NAT gateway, no ALB, no EKS. Flag anything billed hourly.
- Applied and destroyed by scheduled CI workflows, never locally.
