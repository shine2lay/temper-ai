# Task Specification: test-high-m5-scenario-validation

## Problem Statement

M5 Milestone 1 must be validated end-to-end with a realistic scenario to prove the complete self-improvement loop works. This test demonstrates M5's value by automatically finding the best Ollama model for product extraction with measurable quality improvement.

## Acceptance Criteria

- Complete end-to-end test scenario: "Find Best Ollama Model for Product Extraction"
- Test phases:
  1. Baseline period: 100 extractions with llama3.1:8b
  2. M5 triggers: analyze → detect → optimize → experiment
  3. Experiment runs: 4-way test (control + 3 variants), 50 executions each
  4. Winner deployed: qwen2.5:32b
  5. Validation: 100 more executions, verify improvement sustained
- Success metrics:
  - Quality improved: baseline 0.72 → winner 0.91 (+26% improvement)
  - Statistically significant (p < 0.05)
  - M5 ran automatically (minimal manual intervention)
  - Best model discovered through experimentation (not guessing)
  - Improvement sustained over 100+ executions
- Test runs in <30 minutes (with simulated executions)
- Well-documented test output showing each phase

## Implementation Details

```python
def test_m5_ollama_model_selection_scenario():
    """
    End-to-end validation of M5 Milestone 1.

    Scenario: Find best Ollama model for product extraction task.
    """

    # Setup
    db = setup_test_database()
    m5 = M5SelfImprovementLoop(db)
    test_dataset = load_product_test_cases()

    # ============================================
    # PHASE 1: Baseline Period
    # ============================================
    print("\n=== PHASE 1: Baseline Period ===")
    baseline_model = "llama3.1:8b"
    baseline_results = []

    for i, test_case in enumerate(test_dataset[:100]):
        result = run_extraction(
            model=baseline_model,
            description=test_case["description"],
            ground_truth=test_case["ground_truth"]
        )
        baseline_results.append(result)

        # Store in DB for M5
        store_execution(
            agent_name="product_extractor",
            model=baseline_model,
            quality=result["quality"],
            duration=result["duration"],
            output=result["output"]
        )

    baseline_quality = np.mean([r["quality"] for r in baseline_results])
    print(f"Baseline quality: {baseline_quality:.2f}")
    assert 0.70 <= baseline_quality <= 0.75  # Expected range

    # ============================================
    # PHASE 2: M5 Triggers
    # ============================================
    print("\n=== PHASE 2: M5 Analysis & Detection ===")

    # Step 1: Analyze
    m5.run_analysis()

    # Step 2: Detect & Optimize
    m5.run_optimization()

    # Verify experiment created
    experiments = db.get_running_experiments()
    assert len(experiments) == 1
    experiment = experiments[0]

    print(f"Experiment created: {experiment.id}")
    print(f"Testing models: control + {len(experiment.variant_configs)} variants")
    for i, variant in enumerate(experiment.variant_configs):
        print(f"  Variant {i+1}: {variant['inference']['model']}")

    # ============================================
    # PHASE 3: Experiment Runs
    # ============================================
    print("\n=== PHASE 3: Running Experiment ===")

    variant_results = {}
    all_configs = {
        "control": experiment.control_config,
        **{f"variant_{i}": cfg for i, cfg in enumerate(experiment.variant_configs)}
    }

    for variant_id, config in all_configs.items():
        model = config["inference"]["model"]
        print(f"\nTesting {variant_id} ({model})...")

        results = []
        for test_case in test_dataset[100:150]:  # 50 executions per variant
            result = run_extraction(
                model=model,
                description=test_case["description"],
                ground_truth=test_case["ground_truth"]
            )
            results.append(result)

            # Store experiment result
            store_experiment_result(
                experiment_id=experiment.id,
                variant_id=variant_id,
                quality=result["quality"],
                duration=result["duration"]
            )

        avg_quality = np.mean([r["quality"] for r in results])
        avg_speed = np.mean([r["duration"] for r in results])
        variant_results[variant_id] = {
            "model": model,
            "quality": avg_quality,
            "speed": avg_speed
        }

        print(f"  Quality: {avg_quality:.2f}, Speed: {avg_speed:.1f}s")

    # ============================================
    # PHASE 4: Winner Selection & Deployment
    # ============================================
    print("\n=== PHASE 4: Winner Selection ===")

    m5.check_experiments()

    # Verify winner deployed
    deployments = db.get_recent_deployments("product_extractor")
    assert len(deployments) == 1
    deployment = deployments[0]

    winner_model = deployment.new_config["inference"]["model"]
    print(f"Winner: {winner_model}")

    # Verify it's the best model
    best_variant = max(variant_results.items(), key=lambda x: x[1]["quality"])
    assert winner_model == best_variant[1]["model"]

    # Verify quality improved
    winner_quality = best_variant[1]["quality"]
    improvement = (winner_quality - baseline_quality) / baseline_quality * 100
    print(f"Quality: {baseline_quality:.2f} → {winner_quality:.2f} ({improvement:+.1f}%)")
    assert improvement >= 20  # At least 20% improvement

    # ============================================
    # PHASE 5: Validation
    # ============================================
    print("\n=== PHASE 5: Validation ===")

    validation_results = []
    for test_case in test_dataset[200:300]:  # 100 validation runs
        result = run_extraction(
            model=winner_model,
            description=test_case["description"],
            ground_truth=test_case["ground_truth"]
        )
        validation_results.append(result)

    validation_quality = np.mean([r["quality"] for r in validation_results])
    print(f"Validation quality: {validation_quality:.2f}")

    # Verify improvement sustained
    assert validation_quality >= winner_quality * 0.95  # Within 5% of experiment

    # ============================================
    # SUCCESS!
    # ============================================
    print("\n" + "="*50)
    print("✅ M5 MILESTONE 1 VALIDATION SUCCESS!")
    print("="*50)
    print(f"Baseline: {baseline_quality:.2f}")
    print(f"Winner: {winner_quality:.2f} (+{improvement:.1f}%)")
    print(f"Validated: {validation_quality:.2f}")
    print(f"Model: {winner_model}")
    print("="*50)
```

## Test Strategy

1. Run full scenario with real Ollama models
2. Verify each phase completes successfully
3. Verify quality improvement is significant and sustained
4. Verify experiment data stored correctly in DB
5. Generate detailed test report

## Dependencies

- code-med-m5-cli-commands

## Estimated Effort

8-12 hours (scenario implementation, data generation, validation)
