import ast
from copy import deepcopy
from dataclasses import fields, replace
from pathlib import Path
from types import MappingProxyType
import unittest
from unittest.mock import patch

import kairos.construction_audit as audit
from kairos.construction import (
    ConstructionResult,
    ConstructionTerminal,
    construct_explicit_counterfactual,
)
from kairos.construction_audit import (
    ConstructionAuditRecord,
    make_construction_audit_record,
)
from kairos.ids import canonical_json, make_stable_id, sha256_canonical
from kairos.schema import (
    AnswerType,
    ExtractionResult,
    Rejection,
    RejectionReason,
    SplitAssignment,
    TemporalExample,
)


def example(
    *,
    record_id="record:synthetic-original",
    source_id="source:synthetic",
    dataset="synthetic",
    revision="synthetic-v1",
    source_sha256="0" * 64,
    text="Alpha before Beta",
    question="Which happened first?",
    answers=("Alpha",),
    answer_type=AnswerType.EXTRACTIVE,
):
    return TemporalExample(
        record_id=record_id,
        source_id=source_id,
        dataset=dataset,
        split=SplitAssignment(official="validation", internal=None),
        revision=revision,
        source_sha256=source_sha256,
        text=text,
        question=question,
        answers=answers,
        answer_type=answer_type,
    )


def seven_terminal_inputs():
    return (
        (ConstructionTerminal.NO_MARKER, example(text="No temporal relation")),
        (ConstructionTerminal.EXTRACTION_REJECTED, example(text="Alpha while Beta")),
        (
            ConstructionTerminal.TEXT_QUESTION_ALIAS_UNSUPPORTED,
            example(question="Alpha before Beta"),
        ),
        (ConstructionTerminal.REWRITE_REJECTED, example(text="Alpha prior to Beta")),
        (
            ConstructionTerminal.MULTIPLE_ANSWERS_UNSUPPORTED,
            example(answers=("Alpha", "alternate")),
        ),
        (
            ConstructionTerminal.ANSWER_UPDATE_UNKNOWN,
            example(
                question="How many items?",
                answers=("3",),
                answer_type=AnswerType.NUMERIC,
            ),
        ),
        (ConstructionTerminal.RETAINED, example()),
    )


def make_record(value=None, *, input_order=0):
    value = example() if value is None else value
    return make_construction_audit_record(
        input_order=input_order,
        input=value,
        result=construct_explicit_counterfactual(value),
    )


def result_with_details(value, details, *, message="synthetic rejection"):
    result = construct_explicit_counterfactual(value)
    rejection = result.extraction_result.rejection
    if rejection is None:
        raise AssertionError("fixture must have an extraction rejection")
    updated_rejection = Rejection(
        reason=rejection.reason,
        message=message,
        details=details,
    )
    return replace(
        result,
        extraction_result=ExtractionResult(rejection=updated_rejection),
    )


def details_at_depth(depth):
    value = None
    for _ in range(depth):
        value = [value]
    return {"value": value}


def details_max_depth(value, depth=0):
    children = value.values() if isinstance(value, dict) else value if isinstance(value, list) else ()
    return max((details_max_depth(child, depth + 1) for child in children), default=depth)


def details_node_count(value):
    children = value.values() if isinstance(value, dict) else value if isinstance(value, list) else ()
    return 1 + sum(details_node_count(child) for child in children)


def nested_value(value, path):
    for component in path:
        value = value[component]
    return value


class ConstructionAuditContractTests(unittest.TestCase):
    def test_exact_public_surface_fields_versions_and_redacted_repr(self):
        self.assertEqual(
            audit.__all__,
            ("ConstructionAuditRecord", "make_construction_audit_record"),
        )
        self.assertEqual(
            [field.name for field in fields(ConstructionAuditRecord)],
            [
                "audit_record_id",
                "record_fingerprint_sha256",
                "schema_version",
                "construction_version",
                "input_order",
                "input",
                "terminal",
                "outcome",
                "extraction_result",
                "rewrite_result",
                "answer_update",
                "template_id",
                "prospective_pair_id",
                "prospective_counterfactual_record_id",
                "original",
                "counterfactual",
            ],
        )
        record = make_record()
        self.assertEqual(record.schema_version, "construction-audit-v1")
        self.assertEqual(
            record.construction_version, "explicit-marker-construction-v0"
        )
        self.assertEqual(repr(record), "ConstructionAuditRecord(<redacted>)")
        self.assertEqual(str(record), "ConstructionAuditRecord(<redacted>)")

    def test_all_seven_real_terminals_round_trip_canonically(self):
        top_level_keys = [
            "audit_record_id",
            "record_fingerprint_sha256",
            "schema_version",
            "construction_version",
            "input_order",
            "input",
            "terminal",
            "outcome",
            "extraction_result",
            "rewrite_result",
            "answer_update",
            "template_id",
            "prospective_pair_id",
            "prospective_counterfactual_record_id",
            "original",
            "counterfactual",
        ]
        for input_order, (terminal, value) in enumerate(seven_terminal_inputs()):
            with self.subTest(terminal=terminal):
                result = construct_explicit_counterfactual(value)
                self.assertIs(result.terminal, terminal)
                record = make_construction_audit_record(
                    input_order=input_order, input=value, result=result
                )
                primitive = record.to_dict()
                restored = ConstructionAuditRecord.from_dict(primitive)
                self.assertEqual(list(primitive), top_level_keys)
                self.assertEqual(restored, record)
                self.assertEqual(canonical_json(restored.to_dict()), canonical_json(primitive))

    def test_nested_tagged_unions_and_exact_shapes(self):
        retained = make_record().to_dict()
        self.assertEqual(retained["extraction_result"]["kind"], "extraction")
        self.assertEqual(
            retained["rewrite_result"]["kind"], "counterfactual_rewrite"
        )
        self.assertEqual(
            set(retained["answer_update"]), {"status", "value", "reason"}
        )
        self.assertEqual(
            set(retained["input"]),
            {
                "record_id",
                "source_id",
                "dataset",
                "split",
                "revision",
                "source_sha256",
                "text",
                "question",
                "answers",
                "answer_type",
                "events",
                "relations",
                "counterfactual_pair_id",
            },
        )
        self.assertEqual(retained["input"]["events"], [])
        self.assertEqual(retained["input"]["relations"], [])
        self.assertIsNone(retained["input"]["counterfactual_pair_id"])

        no_marker = make_record(example(text="No temporal relation")).to_dict()
        self.assertEqual(no_marker["extraction_result"]["kind"], "rejection")
        self.assertIsNone(no_marker["rewrite_result"])
        self.assertIsNone(no_marker["answer_update"])

        rewrite_rejected = make_record(example(text="Alpha prior to Beta")).to_dict()
        self.assertEqual(rewrite_rejected["rewrite_result"]["kind"], "rejection")

    def test_input_order_is_non_boolean_uint63(self):
        for value in (0, (1 << 63) - 1):
            self.assertEqual(make_record(input_order=value).input_order, value)
        for value in (True, False, -1, 1 << 63, 1.0, "1"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(
                    (TypeError, ValueError), "^invalid construction audit maker input$"
                ):
                    make_record(input_order=value)

    def test_id_formula_and_fingerprint_payload_are_exact(self):
        value = example()
        record = make_record(value, input_order=17)
        expected_id = make_stable_id(
            "construction-audit",
            {
                "schema_version": "construction-audit-v1",
                "construction_version": "explicit-marker-construction-v0",
                "dataset": value.dataset,
                "revision": value.revision,
                "source_id": value.source_id,
                "input_record_id": value.record_id,
                "source_sha256": value.source_sha256,
            },
        )
        self.assertEqual(record.audit_record_id, expected_id)
        primitive = record.to_dict()
        fingerprint_payload = {
            key: item
            for key, item in primitive.items()
            if key != "record_fingerprint_sha256"
        }
        self.assertEqual(
            record.record_fingerprint_sha256,
            sha256_canonical(fingerprint_payload),
        )

    def test_id_uses_only_frozen_source_identity_and_fingerprint_uses_diagnostics(self):
        base = example(text="No temporal relation")
        first = make_record(base, input_order=0)
        changed_order = make_record(base, input_order=1)
        self.assertEqual(first.audit_record_id, changed_order.audit_record_id)
        self.assertNotEqual(
            first.record_fingerprint_sha256,
            changed_order.record_fingerprint_sha256,
        )

        for field_name, changed in (
            ("dataset", "synthetic-other"),
            ("revision", "synthetic-v2"),
            ("source_id", "source:other"),
            ("record_id", "record:other"),
            ("source_sha256", "1" * 64),
        ):
            with self.subTest(field=field_name):
                altered = replace(base, **{field_name: changed})
                self.assertNotEqual(first.audit_record_id, make_record(altered).audit_record_id)

        details_result = result_with_details(base, {"diagnostic": "changed"})
        with_details = make_construction_audit_record(
            input_order=0, input=base, result=details_result
        )
        self.assertEqual(first.audit_record_id, with_details.audit_record_id)
        self.assertNotEqual(
            first.record_fingerprint_sha256,
            with_details.record_fingerprint_sha256,
        )

        first_message = make_construction_audit_record(
            input_order=0,
            input=base,
            result=result_with_details(base, {}, message="first rejection message"),
        )
        second_message = make_construction_audit_record(
            input_order=0,
            input=base,
            result=result_with_details(base, {}, message="second rejection message"),
        )
        self.assertEqual(first_message.audit_record_id, second_message.audit_record_id)
        self.assertNotEqual(
            first_message.record_fingerprint_sha256,
            second_message.record_fingerprint_sha256,
        )

    def test_fixed_version_literals_resist_attacker_recomputation(self):
        for key, attacker_value in (
            ("schema_version", "attacker-schema"),
            ("construction_version", "attacker-construction"),
        ):
            with self.subTest(key=key):
                primitive = make_record().to_dict()
                primitive[key] = attacker_value
                input_value = primitive["input"]
                primitive["audit_record_id"] = make_stable_id(
                    "construction-audit",
                    {
                        "schema_version": primitive["schema_version"],
                        "construction_version": primitive["construction_version"],
                        "dataset": input_value["dataset"],
                        "revision": input_value["revision"],
                        "source_id": input_value["source_id"],
                        "input_record_id": input_value["record_id"],
                        "source_sha256": input_value["source_sha256"],
                    },
                )
                primitive["record_fingerprint_sha256"] = sha256_canonical(
                    {
                        field: item
                        for field, item in primitive.items()
                        if field != "record_fingerprint_sha256"
                    }
                )
                with self.assertRaisesRegex(
                    ValueError, "^invalid construction audit mapping$"
                ) as caught:
                    ConstructionAuditRecord.from_dict(primitive)
                self.assertNotIn(attacker_value, str(caught.exception))

    def test_stale_id_and_fingerprint_have_fixed_errors(self):
        primitive = make_record().to_dict()
        stale_id = deepcopy(primitive)
        stale_id["audit_record_id"] = "construction-audit:" + "0" * 64
        with self.assertRaisesRegex(ValueError, "^construction audit ID mismatch$"):
            ConstructionAuditRecord.from_dict(stale_id)

        stale_fingerprint = deepcopy(primitive)
        stale_fingerprint["record_fingerprint_sha256"] = "0" * 64
        with self.assertRaisesRegex(
            ValueError, "^construction audit fingerprint mismatch$"
        ):
            ConstructionAuditRecord.from_dict(stale_fingerprint)

    def test_details_are_deep_frozen_copied_and_freshly_thawed(self):
        value = example(text="No temporal relation")
        original = {"items": [{"flag": True, "count": 2, "ratio": 1.25}]}
        result = result_with_details(value, original)
        record = make_construction_audit_record(input_order=0, input=value, result=result)
        details = record.extraction_result.rejection.details
        self.assertIsInstance(details, MappingProxyType)
        self.assertIsInstance(details["items"], tuple)
        self.assertIsInstance(details["items"][0], MappingProxyType)
        original["items"][0]["count"] = 99
        original["items"].append("late mutation")
        first = record.to_dict()
        second = record.to_dict()
        first_details = first["extraction_result"]["value"]["details"]
        second_details = second["extraction_result"]["value"]["details"]
        self.assertEqual(first_details["items"][0]["count"], 2)
        self.assertIsNot(first_details, second_details)
        self.assertIsNot(first_details["items"], second_details["items"])
        first_details["items"][0]["count"] = -1
        self.assertEqual(second_details["items"][0]["count"], 2)
        self.assertEqual(record.to_dict(), second)

        proxy = MappingProxyType({"nested": (MappingProxyType({"x": 1}),)})
        proxy_result = result_with_details(value, proxy)
        proxy_record = make_construction_audit_record(
            input_order=0, input=value, result=proxy_result
        )
        frozen = proxy_record.extraction_result.rejection.details
        self.assertIsNot(frozen, proxy)
        self.assertIsNot(frozen["nested"], proxy["nested"])
        self.assertIsNot(frozen["nested"][0], proxy["nested"][0])

    def test_details_depth_node_and_utf8_boundaries(self):
        value = example(text="No temporal relation")
        accepted = (
            details_at_depth(15),
            {"items": [None] * 4094},
            {"x": "a" * (65536 - 8)},
        )
        self.assertEqual(details_max_depth(accepted[0]), 16)
        self.assertEqual(details_node_count(accepted[1]), 4096)
        self.assertEqual(len(canonical_json(accepted[2]).encode("utf-8")), 65536)
        for details in accepted:
            with self.subTest(kind=type(details).__name__):
                result = result_with_details(value, details)
                make_construction_audit_record(input_order=0, input=value, result=result)

        rejected = (
            details_at_depth(16),
            {"items": [None] * 4095},
            {"x": "a" * (65537 - 8)},
        )
        self.assertEqual(details_max_depth(rejected[0]), 17)
        self.assertEqual(details_node_count(rejected[1]), 4097)
        self.assertEqual(len(canonical_json(rejected[2]).encode("utf-8")), 65537)
        for details in rejected:
            with self.subTest(kind=type(details).__name__):
                result = result_with_details(value, details)
                with self.assertRaisesRegex(
                    ValueError, "^invalid construction audit maker input$"
                ):
                    make_construction_audit_record(
                        input_order=0, input=value, result=result
                    )

    def test_details_depth_and_node_gates_precede_byte_serialization(self):
        value = example(text="No temporal relation")
        for details in (details_at_depth(16), {"items": [None] * 4095}):
            result = result_with_details(value, details)
            with self.subTest(nodes=len(details.get("items", ()))):
                with patch.object(
                    audit, "canonical_json", wraps=canonical_json
                ) as canonical_spy:
                    with self.assertRaisesRegex(
                        ValueError, "^invalid construction audit maker input$"
                    ):
                        make_construction_audit_record(
                            input_order=0, input=value, result=result
                        )
                    canonical_spy.assert_not_called()

    def test_details_domain_rejects_nonfinite_nonstring_keys_and_objects(self):
        value = example(text="No temporal relation")
        for details in (
            {"x": float("nan")},
            {"x": float("inf")},
            {1: "not a string key"},
            {"x": object()},
        ):
            with self.subTest(details=repr(details)):
                result = result_with_details(value, details)
                with self.assertRaisesRegex(
                    (TypeError, ValueError), "^invalid construction audit maker input$"
                ):
                    make_construction_audit_record(
                        input_order=0, input=value, result=result
                    )

    def test_direct_constructor_also_refreezes_details_before_fingerprint_check(self):
        value = example(text="No temporal relation")
        mutable = {"nested": [{"x": 1}]}
        result = result_with_details(value, mutable)
        normalized = make_construction_audit_record(
            input_order=0, input=value, result=result
        )
        raw_rejection = result.extraction_result.rejection
        raw_extraction_result = ExtractionResult(rejection=raw_rejection)
        rebuilt = ConstructionAuditRecord(
            audit_record_id=normalized.audit_record_id,
            record_fingerprint_sha256=normalized.record_fingerprint_sha256,
            schema_version=normalized.schema_version,
            construction_version=normalized.construction_version,
            input_order=normalized.input_order,
            input=normalized.input,
            terminal=normalized.terminal,
            outcome=normalized.outcome,
            extraction_result=raw_extraction_result,
            rewrite_result=normalized.rewrite_result,
            answer_update=normalized.answer_update,
            template_id=normalized.template_id,
            prospective_pair_id=normalized.prospective_pair_id,
            prospective_counterfactual_record_id=(
                normalized.prospective_counterfactual_record_id
            ),
            original=normalized.original,
            counterfactual=normalized.counterfactual,
        )
        self.assertIsInstance(rebuilt.extraction_result.rejection.details, MappingProxyType)
        self.assertIsNot(rebuilt.extraction_result.rejection.details, mutable)
        mutable["nested"][0]["x"] = 2
        self.assertEqual(
            rebuilt.extraction_result.rejection.details["nested"][0]["x"], 1
        )

    def test_from_dict_rejects_schema_mutations_without_payload_leaks(self):
        base = make_record().to_dict()
        mutations = []
        missing = deepcopy(base)
        del missing["input_order"]
        mutations.append(missing)
        extra = deepcopy(base)
        extra["SENTINEL-extra"] = 1
        mutations.append(extra)
        bad_terminal = deepcopy(base)
        bad_terminal["terminal"] = "SENTINEL-terminal"
        mutations.append(bad_terminal)
        bad_nested_extra = deepcopy(base)
        bad_nested_extra["input"]["SENTINEL-nested"] = 1
        mutations.append(bad_nested_extra)
        bad_nested_missing = deepcopy(base)
        del bad_nested_missing["outcome"]["final_retained"]
        mutations.append(bad_nested_missing)
        bad_tag = deepcopy(base)
        bad_tag["extraction_result"]["kind"] = "SENTINEL-kind"
        mutations.append(bad_tag)
        bad_order = deepcopy(base)
        bad_order["input_order"] = True
        mutations.append(bad_order)

        for mutation in mutations:
            with self.subTest(keys=tuple(mutation)):
                with self.assertRaisesRegex(
                    ValueError, "^invalid construction audit mapping$"
                ) as caught:
                    ConstructionAuditRecord.from_dict(mutation)
                self.assertNotIn("SENTINEL", str(caught.exception))

        with self.assertRaisesRegex(
            TypeError, "^construction audit value must be a mapping$"
        ):
            ConstructionAuditRecord.from_dict([])

    def test_primitive_scalar_validation_is_explicit_and_payload_free(self):
        retained = make_record().to_dict()
        rejected = make_record(example(text="No temporal relation")).to_dict()
        cases = (
            (retained, ("input", "question"), 1),
            (retained, ("input", "question"), None),
            (retained, ("input", "text"), True),
            (retained, ("input", "record_id"), False),
            (retained, ("input", "source_id"), 1),
            (retained, ("input", "dataset"), []),
            (retained, ("input", "revision"), {}),
            (retained, ("input", "source_sha256"), True),
            (retained, ("input", "answer_type"), False),
            (retained, ("input", "answer_type"), "SENTINEL-answer-type"),
            (retained, ("input", "answers", 0), True),
            (retained, ("input", "counterfactual_pair_id"), 1),
            (retained, ("input", "split", "official"), True),
            (retained, ("input", "split", "internal"), 1),
            (retained, ("input", "split", "internal"), "SENTINEL-internal-split"),
            (retained, ("original", "events", 0, "event_id"), True),
            (retained, ("original", "events", 0, "text"), 1),
            (retained, ("original", "events", 0, "char_span", "start"), False),
            (retained, ("original", "relations", 0, "source_event_id"), 1),
            (retained, ("original", "relations", 0, "target_event_id"), False),
            (retained, ("original", "relations", 0, "relation"), True),
            (
                retained,
                ("original", "relations", 0, "relation"),
                "SENTINEL-relation",
            ),
            (retained, ("original", "relations", 0, "marker"), 1),
            (retained, ("original", "relations", 0, "provenance"), []),
            (retained, ("outcome", "temporal_filtered"), 1),
            (retained, ("terminal",), True),
            (retained, ("schema_version",), False),
            (retained, ("template_id",), 1),
            (retained, ("prospective_pair_id",), False),
            (retained, ("prospective_counterfactual_record_id",), []),
            (retained, ("extraction_result", "kind"), True),
            (retained, ("extraction_result", "kind"), "SENTINEL-extraction-tag"),
            (retained, ("extraction_result", "value", "text"), False),
            (retained, ("extraction_result", "value", "marker"), 1),
            (retained, ("rewrite_result", "kind"), False),
            (retained, ("rewrite_result", "kind"), "SENTINEL-rewrite-tag"),
            (retained, ("rewrite_result", "value", "original_text"), 1),
            (retained, ("rewrite_result", "value", "template_id"), True),
            (retained, ("answer_update", "status"), False),
            (retained, ("answer_update", "status"), "SENTINEL-answer-status"),
            (retained, ("answer_update", "value"), 1),
            (retained, ("answer_update", "reason"), []),
            (rejected, ("extraction_result", "value", "reason"), True),
            (rejected, ("extraction_result", "value", "message"), 1),
            (rejected, ("extraction_result", "value", "message"), None),
        )
        for index, (source, path, bad_value) in enumerate(cases):
            mutation = deepcopy(source)
            parent = nested_value(mutation, path[:-1]) if path[:-1] else mutation
            parent[path[-1]] = bad_value
            with self.subTest(index=index, path=path):
                with self.assertRaisesRegex(
                    ValueError, "^invalid construction audit mapping$"
                ) as caught:
                    ConstructionAuditRecord.from_dict(mutation)
                self.assertEqual(str(caught.exception), "invalid construction audit mapping")

    def test_parser_rejects_d011_optional_matrix_mutations_before_fingerprint(self):
        retained = make_record().to_dict()
        no_marker = make_record(example(text="No temporal relation")).to_dict()
        unknown = make_record(
            example(
                question="How many items?",
                answers=("3",),
                answer_type=AnswerType.NUMERIC,
            )
        ).to_dict()
        mutations = []

        no_marker_with_rewrite = deepcopy(no_marker)
        no_marker_with_rewrite["rewrite_result"] = deepcopy(retained["rewrite_result"])
        mutations.append(("no-marker-rewrite", no_marker_with_rewrite))

        retained_without_update = deepcopy(retained)
        retained_without_update["answer_update"] = None
        mutations.append(("retained-answer-update", retained_without_update))

        unknown_without_update = deepcopy(unknown)
        unknown_without_update["answer_update"] = None
        mutations.append(("unknown-answer-update", unknown_without_update))

        outcome_mismatch = deepcopy(retained)
        outcome_mismatch["outcome"]["final_retained"] = False
        mutations.append(("outcome", outcome_mismatch))

        for field_name in (
            "template_id",
            "prospective_pair_id",
            "prospective_counterfactual_record_id",
        ):
            partial_identity = deepcopy(retained)
            partial_identity[field_name] = None
            mutations.append(("partial-" + field_name, partial_identity))

        original_missing = deepcopy(retained)
        original_missing["original"] = None
        mutations.append(("original-half", original_missing))
        counterfactual_missing = deepcopy(retained)
        counterfactual_missing["counterfactual"] = None
        mutations.append(("counterfactual-half", counterfactual_missing))

        for name, mutation in mutations:
            with self.subTest(matrix=name):
                with self.assertRaisesRegex(
                    ValueError, "^invalid construction audit mapping$"
                ):
                    ConstructionAuditRecord.from_dict(mutation)

    def test_every_nested_mapping_rejects_missing_and_extra_keys(self):
        retained = make_record().to_dict()
        rejected = make_record(example(text="No temporal relation")).to_dict()
        mappings = (
            ("top", retained, ()),
            ("split", retained, ("input", "split")),
            ("example", retained, ("input",)),
            ("event", retained, ("original", "events", 0)),
            ("span", retained, ("original", "events", 0, "char_span")),
            ("relation", retained, ("original", "relations", 0)),
            ("outcome", retained, ("outcome",)),
            ("extraction-tag", retained, ("extraction_result",)),
            ("extraction", retained, ("extraction_result", "value")),
            (
                "extraction-event",
                retained,
                ("extraction_result", "value", "event_a"),
            ),
            (
                "extraction-relation",
                retained,
                ("extraction_result", "value", "relation"),
            ),
            ("rewrite-tag", retained, ("rewrite_result",)),
            ("rewrite", retained, ("rewrite_result", "value")),
            ("answer-update", retained, ("answer_update",)),
            ("rejection", rejected, ("extraction_result", "value")),
        )
        for name, source, path in mappings:
            target = nested_value(source, path) if path else source
            removed_key = next(iter(target))
            for mode in ("missing", "extra"):
                mutation = deepcopy(source)
                mutable_target = nested_value(mutation, path) if path else mutation
                if mode == "missing":
                    del mutable_target[removed_key]
                else:
                    mutable_target["SENTINEL-extra-key"] = None
                with self.subTest(mapping=name, mode=mode):
                    with self.assertRaisesRegex(
                        ValueError, "^invalid construction audit mapping$"
                    ) as caught:
                        ConstructionAuditRecord.from_dict(mutation)
                    self.assertNotIn("SENTINEL", str(caught.exception))

    def test_from_dict_detaches_all_caller_containers_and_to_dict_is_fresh(self):
        value = example(text="No temporal relation", answers=("answer-one",))
        result = result_with_details(value, {"nested": [{"x": 1}]})
        source_record = make_construction_audit_record(
            input_order=0, input=value, result=result
        )
        raw = source_record.to_dict()
        restored = ConstructionAuditRecord.from_dict(raw)
        before = canonical_json(restored.to_dict())
        raw["input"]["answers"].append("late-answer")
        raw["extraction_result"]["value"]["details"]["nested"][0]["x"] = 99
        raw["extraction_result"]["value"]["details"]["nested"].append("late")
        self.assertEqual(canonical_json(restored.to_dict()), before)

        first = restored.to_dict()
        second = restored.to_dict()
        self.assertIsNot(first, second)
        self.assertIsNot(first["input"], second["input"])
        self.assertIsNot(first["input"]["answers"], second["input"]["answers"])
        first_details = first["extraction_result"]["value"]["details"]
        second_details = second["extraction_result"]["value"]["details"]
        self.assertIsNot(first_details, second_details)
        self.assertIsNot(first_details["nested"], second_details["nested"])
        self.assertIsNot(first_details["nested"][0], second_details["nested"][0])

    def test_fingerprint_changes_for_each_of_the_other_fifteen_fields(self):
        primitive = make_record(input_order=9).to_dict()
        payload = {
            key: item
            for key, item in primitive.items()
            if key != "record_fingerprint_sha256"
        }
        base_fingerprint = sha256_canonical(payload)
        mutations = {
            "audit_record_id": lambda value: value.__setitem__(
                "audit_record_id", "construction-audit:" + "f" * 64
            ),
            "schema_version": lambda value: value.__setitem__("schema_version", "v2"),
            "construction_version": lambda value: value.__setitem__(
                "construction_version", "v2"
            ),
            "input_order": lambda value: value.__setitem__("input_order", 10),
            "input": lambda value: value["input"].__setitem__("question", "changed"),
            "terminal": lambda value: value.__setitem__("terminal", "changed"),
            "outcome": lambda value: value["outcome"].__setitem__(
                "final_retained", False
            ),
            "extraction_result": lambda value: value["extraction_result"][
                "value"
            ].__setitem__("marker", "changed"),
            "rewrite_result": lambda value: value["rewrite_result"][
                "value"
            ].__setitem__("template_id", "changed"),
            "answer_update": lambda value: value["answer_update"].__setitem__(
                "value", "changed"
            ),
            "template_id": lambda value: value.__setitem__("template_id", "changed"),
            "prospective_pair_id": lambda value: value.__setitem__(
                "prospective_pair_id", "changed"
            ),
            "prospective_counterfactual_record_id": lambda value: value.__setitem__(
                "prospective_counterfactual_record_id", "changed"
            ),
            "original": lambda value: value["original"].__setitem__(
                "question", "changed"
            ),
            "counterfactual": lambda value: value["counterfactual"].__setitem__(
                "question", "changed"
            ),
        }
        self.assertEqual(set(mutations), set(payload))
        for field_name, mutate in mutations.items():
            changed = deepcopy(payload)
            mutate(changed)
            with self.subTest(field=field_name):
                self.assertNotEqual(sha256_canonical(changed), base_fingerprint)

    def test_maker_and_parser_enforce_crosslinks_and_complete_roles(self):
        source = example()
        result = construct_explicit_counterfactual(source)
        mismatched_input = replace(source, record_id="record:different")
        with self.assertRaisesRegex(
            ValueError, "^invalid construction audit maker input$"
        ):
            make_construction_audit_record(
                input_order=0, input=mismatched_input, result=result
            )

        primitive = make_record(source).to_dict()
        partial = deepcopy(primitive)
        partial["original"] = None
        with self.assertRaisesRegex(ValueError, "^invalid construction audit mapping$"):
            ConstructionAuditRecord.from_dict(partial)

        colliding = deepcopy(primitive)
        pair_id = colliding["input"]["record_id"]
        colliding["prospective_pair_id"] = pair_id
        colliding["original"]["counterfactual_pair_id"] = pair_id
        colliding["counterfactual"]["counterfactual_pair_id"] = pair_id
        with self.assertRaisesRegex(ValueError, "^invalid construction audit mapping$"):
            ConstructionAuditRecord.from_dict(colliding)

        wrong_final_id = deepcopy(primitive)
        wrong_final_id["counterfactual"]["record_id"] = "record:wrong-final"
        with self.assertRaisesRegex(ValueError, "^invalid construction audit mapping$"):
            ConstructionAuditRecord.from_dict(wrong_final_id)

    def test_retained_crosslink_matrix_fails_closed(self):
        primitive = make_record().to_dict()
        changes = []

        for field_name, changed_value in (
            ("record_id", "record:changed-original"),
            ("source_id", "source:changed"),
            ("dataset", "changed-dataset"),
            ("split", {"official": "test", "internal": None}),
            ("revision", "changed-revision"),
            ("source_sha256", "1" * 64),
            ("text", "Gamma before Delta"),
            ("question", "Changed question?"),
            ("answers", ["changed-answer"]),
            ("answer_type", "free_generation"),
        ):
            changes.append(
                (
                    "original-" + field_name,
                    lambda value, field_name=field_name, changed_value=changed_value: value[
                        "original"
                    ].__setitem__(field_name, changed_value),
                )
            )

        for field_name, changed_value in (
            ("source_id", "source:changed"),
            ("dataset", "changed-dataset"),
            ("split", {"official": "test", "internal": None}),
            ("revision", "changed-revision"),
            ("source_sha256", "1" * 64),
            ("question", "Changed question?"),
            ("answer_type", "free_generation"),
        ):
            changes.append(
                (
                    "counterfactual-" + field_name,
                    lambda value, field_name=field_name, changed_value=changed_value: value[
                        "counterfactual"
                    ].__setitem__(field_name, changed_value),
                )
            )

        changes.extend(
            (
                (
                    "counterfactual-text-vs-rewrite",
                    lambda value: value["counterfactual"].__setitem__(
                        "text", value["counterfactual"]["text"] + "!"
                    ),
                ),
                (
                    "prospective-counterfactual-role",
                    lambda value: value.__setitem__(
                        "prospective_counterfactual_record_id", "record:changed"
                    ),
                ),
                (
                    "pair-role-collision",
                    lambda value: value.__setitem__(
                        "prospective_pair_id", value["input"]["record_id"]
                    ),
                ),
                (
                    "original-pair",
                    lambda value: value["original"].__setitem__(
                        "counterfactual_pair_id", "counterfactual-pair:changed"
                    ),
                ),
                (
                    "counterfactual-pair",
                    lambda value: value["counterfactual"].__setitem__(
                        "counterfactual_pair_id", "counterfactual-pair:changed"
                    ),
                ),
                (
                    "original-events",
                    lambda value: value["original"].__setitem__(
                        "events", list(reversed(value["original"]["events"]))
                    ),
                ),
                (
                    "original-relations",
                    lambda value: value["original"].__setitem__("relations", []),
                ),
                (
                    "counterfactual-events",
                    lambda value: value["counterfactual"].__setitem__(
                        "events", list(reversed(value["counterfactual"]["events"]))
                    ),
                ),
                (
                    "counterfactual-relations",
                    lambda value: value["counterfactual"].__setitem__(
                        "relations", []
                    ),
                ),
                (
                    "counterfactual-answer",
                    lambda value: value["counterfactual"].__setitem__(
                        "answers", ["changed-answer"]
                    ),
                ),
                (
                    "answer-update",
                    lambda value: value["answer_update"].__setitem__(
                        "value", "changed-answer"
                    ),
                ),
                (
                    "rewrite",
                    lambda value: value["rewrite_result"]["value"].__setitem__(
                        "template_id", "template:changed"
                    ),
                ),
            )
        )

        for name, mutate in changes:
            mutation = deepcopy(primitive)
            mutate(mutation)
            with self.subTest(crosslink=name):
                with self.assertRaisesRegex(
                    ValueError, "^invalid construction audit mapping$"
                ):
                    ConstructionAuditRecord.from_dict(mutation)

    def test_retained_role_collisions_fail_with_related_links_preserved(self):
        primitive = make_record().to_dict()

        pair_equals_counterfactual = deepcopy(primitive)
        counterfactual_id = pair_equals_counterfactual[
            "prospective_counterfactual_record_id"
        ]
        pair_equals_counterfactual["prospective_pair_id"] = counterfactual_id
        pair_equals_counterfactual["original"][
            "counterfactual_pair_id"
        ] = counterfactual_id
        pair_equals_counterfactual["counterfactual"][
            "counterfactual_pair_id"
        ] = counterfactual_id

        counterfactual_equals_input = deepcopy(primitive)
        input_id = counterfactual_equals_input["input"]["record_id"]
        counterfactual_equals_input[
            "prospective_counterfactual_record_id"
        ] = input_id
        counterfactual_equals_input["counterfactual"]["record_id"] = input_id

        for name, mutation in (
            ("pair-equals-prospective-counterfactual", pair_equals_counterfactual),
            ("prospective-counterfactual-equals-input", counterfactual_equals_input),
        ):
            with self.subTest(role=name):
                with self.assertRaisesRegex(
                    ValueError, "^invalid construction audit mapping$"
                ):
                    ConstructionAuditRecord.from_dict(mutation)

    def test_payloads_are_present_only_in_explicit_serialization(self):
        text_sentinel = "SENTINEL-private-text"
        question_sentinel = "SENTINEL-private-question"
        answer_sentinel = "SENTINEL-private-answer"
        diagnostic_sentinel = "SENTINEL-private-diagnostic"
        value = example(
            text=text_sentinel,
            question=question_sentinel,
            answers=(answer_sentinel,),
        )
        result = result_with_details(
            value,
            {"private": diagnostic_sentinel},
            message=diagnostic_sentinel,
        )
        record = make_construction_audit_record(input_order=0, input=value, result=result)
        serialized = canonical_json(record.to_dict())
        for sentinel in (
            text_sentinel,
            question_sentinel,
            answer_sentinel,
            diagnostic_sentinel,
        ):
            self.assertNotIn(sentinel, repr(record))
            self.assertNotIn(sentinel, str(record))
            self.assertIn(sentinel, serialized)

        malformed = record.to_dict()
        malformed["extraction_result"]["value"]["reason"] = diagnostic_sentinel
        with self.assertRaisesRegex(
            ValueError, "^invalid construction audit mapping$"
        ) as caught:
            ConstructionAuditRecord.from_dict(malformed)
        self.assertNotIn(diagnostic_sentinel, str(caught.exception))

    def test_static_module_has_no_io_or_ambient_effects(self):
        repo_root = Path(__file__).resolve().parents[1]
        module_path = (repo_root / "src/kairos/construction_audit.py").resolve()
        self.assertTrue(module_path.is_relative_to(repo_root.resolve()))
        tree = ast.parse(module_path.read_text(encoding="utf-8"))
        banned_modules = {
            "argparse",
            "json",
            "logging",
            "os",
            "pathlib",
            "shutil",
            "socket",
            "subprocess",
            "sys",
            "tempfile",
            "urllib",
        }
        imports = set()
        calls = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module.split(".")[0])
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    calls.add(node.func.id)
                elif isinstance(node.func, ast.Attribute):
                    calls.add(node.func.attr)
        self.assertFalse(imports.intersection(banned_modules))
        self.assertFalse(
            calls.intersection(
                {
                    "asdict",
                    "open",
                    "print",
                    "run",
                    "Popen",
                    "write_text",
                    "write_bytes",
                }
            )
        )


if __name__ == "__main__":
    unittest.main()
