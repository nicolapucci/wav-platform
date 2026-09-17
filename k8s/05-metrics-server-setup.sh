#!/bin/sh
# Prerequisito per gli HorizontalPodAutoscaler in questa cartella: senza
# metrics-server, "kubectl top" e ogni HPA restano bloccati su "<unknown>"
# (nessuna sorgente di metriche CPU/memoria nel cluster).
#
# Non e' un manifest applicativo (niente "namespace: wav-platform" - vive in
# kube-system, e' una capacita' del cluster, non un componente di questa app),
# quindi resta fuori dal flusso "kubectl apply -f k8s/": va eseguito una volta
# sola per cluster, con questi due comandi (nota il .sh: kubectl apply su una
# directory ignora i file che non sono .yaml/.yml/.json).
#
# La patch "--kubelet-insecure-tls" serve perche' il certificato del kubelet
# sui nodi kind (il cluster dietro "Kubernetes di Docker Desktop", vedi
# desktop-control-plane in `docker ps`) non e' firmato da una CA che
# metrics-server si fida di default - senza, resta in CrashLoopBackOff.

kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml
kubectl patch deployment metrics-server -n kube-system --type='json' \
  -p='[{"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--kubelet-insecure-tls"}]'
