#!/bin/bash
# Run seed.py as a Job inside the cluster, with the app image (Python + requests).
#   deploy/umbrella/seed-job.sh [namespace] [image]
set -euo pipefail
NS=${1:-umbrella}
IMAGE=${2:-catenax-simplified:latest}
HERE=$(cd "$(dirname "$0")" && pwd)
kubectl -n "$NS" create configmap cxs-seed --dry-run=client -o yaml \
  --from-file=seed.py="$HERE/seed.py" \
  --from-file=participants.json="$HERE/participants.json" \
  --from-file=mock_participant.py="$HERE/../../backend/devtools/mock_participant.py" | kubectl apply -f -
kubectl -n "$NS" delete job cxs-seed --ignore-not-found
kubectl -n "$NS" apply -f - <<YAML
apiVersion: batch/v1
kind: Job
metadata:
  name: cxs-seed
spec:
  backoffLimit: 3
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: seed
          image: $IMAGE
          imagePullPolicy: IfNotPresent
          command: ["python", "/seed/seed.py", "--config", "/seed/participants.json"]
          volumeMounts:
            - {name: seed, mountPath: /seed}
      volumes:
        - name: seed
          configMap: {name: cxs-seed}
YAML
kubectl -n "$NS" wait --for=condition=complete job/cxs-seed --timeout=300s
kubectl -n "$NS" logs job/cxs-seed
