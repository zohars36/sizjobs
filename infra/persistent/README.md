# infra/persistent

Terraform for AWS resources that survive the nightly teardown (Part B only).

Examples: Terraform state bucket, private data bucket, ECR/GHCR-related IAM,
SSM parameters, Route 53 zone, the OIDC role GitHub Actions uses.

- Every resource is tagged `project=sizjobs` and `layer=persistent`.
- Changes are applied by CI on merge to `main`. Never run `terraform apply`
  or `terraform destroy` locally.
- Part A stand-ins: SeaweedFS for S3, `~/.config/sizjobs/.env` for SSM.
