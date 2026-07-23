# Phase 03 Kairos Tensor Core

- status: `COMPLETE / DEVELOPMENT_VERIFIED`
- implementation_commit: `c178d150bbfc8d4626ea70cd4e91c3a7ead13ec6`
- date: 2026-07-23 CST
- production_data/model/GPU: none
- formal_run: none

## Implemented formula path

`src/kairos/modeling.py` implements the independently reconstructed trainable
layers after a backbone supplies contextual hidden states:

1. strict mean pooling of event token spans;
2. linear latent start and `softplus(raw_duration)+1e-6` duration, with
   `end=start+duration`;
3. exact ordered pair geometry
   `[s_i,e_i,s_j,e_j,s_j-e_i,s_i-e_j,d_i,d_j]`;
4. five-way known-relation logits/probabilities over directed non-self pairs;
5. masked mean graph pooling;
6. answer-span pooling and shared-space
   `[u;g;u*g]` candidate scoring;
7. answer CE, known-relation CE and counterfactual-relation CE;
8. Pair-MLP same-supervision baseline with the same masks, relation labels,
   graph pooling and candidate scorer but no interval projection.

The fixed relation index order is `precedes, follows, overlaps, contains,
during`. `unknown` and padding use `-100`; labels on self/padded pairs are an
error and do not enter either relation loss or graph pooling.

## Independent defaults

The paper does not publish executable modules or all tensor choices. This
implementation therefore explicitly labels the following project defaults:

- mean span pooling;
- directed non-self pair graph;
- mean pooling over valid relation distributions;
- minimum duration offset `1e-6` for numerical strict positivity;
- shared answer/graph size 256;
- Pair-MLP pair features `[h_i,h_j,h_i-h_j,h_i*h_j]` and hidden size 256.

These values may be changed only through a recorded configuration and must not
be described as recovered author settings.

## Verification

- focused CPU synthetic suite: 14/14 passed
- full repository suite: 427/427 passed in 13.087 seconds
- synthetic full forward, combined objective and backward propagation passed
- exact geometry ordering, positive duration/end identity, source/padding masks,
  no-pair graph zero, candidate padding, unknown labels, invalid label placement,
  counterfactual objective and Pair-MLP output contract are covered
- `CUDA_VISIBLE_DEVICES` was empty; CPU threads were fixed to 2; no backbone,
  model weights, production record or artifact was loaded

## Remaining end-to-end work

This core does not extract event mentions, tokenize spans, run Qwen, generate
candidate pools, parse prompt outputs, train LoRA or publish predictions. The
next safe step is a deterministic prompt/output and backbone-batch interface,
tested without loading the 7B model. A separate resource-gated clean-commit
smoke run is required before any production inference.
