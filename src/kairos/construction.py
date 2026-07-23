"""Deterministic in-memory explicit-marker counterfactual construction."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum

from .counterfactual import rewrite_counterfactual, update_answer
from .events import extract_explicit_relation
from .ids import make_stable_id
from .io import ConstructionOutcome
from .schema import (
    AnswerStatus,
    AnswerUpdate,
    CounterfactualRewrite,
    Extraction,
    ExtractionResult,
    Relation,
    RejectionReason,
    TemporalExample,
)


class ConstructionTerminal(str, Enum):
    NO_MARKER = "no_marker"
    EXTRACTION_REJECTED = "extraction_rejected"
    TEXT_QUESTION_ALIAS_UNSUPPORTED = "text_question_alias_unsupported"
    REWRITE_REJECTED = "rewrite_rejected"
    MULTIPLE_ANSWERS_UNSUPPORTED = "multiple_answers_unsupported"
    ANSWER_UPDATE_UNKNOWN = "answer_update_unknown"
    RETAINED = "retained"


@dataclass(frozen=True)
class ConstructionResult:
    input_record_id: str
    outcome: ConstructionOutcome
    terminal: ConstructionTerminal
    extraction_result: ExtractionResult
    rewrite_result: CounterfactualRewrite | ExtractionResult | None
    answer_update: AnswerUpdate | None
    template_id: str | None
    prospective_pair_id: str | None
    prospective_counterfactual_record_id: str | None
    original: TemporalExample | None
    counterfactual: TemporalExample | None

    def __post_init__(self) -> None:
        if not isinstance(self.input_record_id, str):
            raise TypeError("input_record_id must be a string")
        if not self.input_record_id.strip():
            raise ValueError("input_record_id must be non-empty")
        if not isinstance(self.outcome, ConstructionOutcome):
            raise TypeError("outcome must be a ConstructionOutcome")
        if not isinstance(self.terminal, ConstructionTerminal):
            raise TypeError("terminal must be a ConstructionTerminal")
        if not isinstance(self.extraction_result, ExtractionResult):
            raise TypeError("extraction_result must be an ExtractionResult")
        if self.rewrite_result is not None and not isinstance(
            self.rewrite_result, (CounterfactualRewrite, ExtractionResult)
        ):
            raise TypeError("rewrite_result has an invalid type")
        if self.answer_update is not None and not isinstance(self.answer_update, AnswerUpdate):
            raise TypeError("answer_update must be an AnswerUpdate or None")
        for name in (
            "template_id",
            "prospective_pair_id",
            "prospective_counterfactual_record_id",
        ):
            value = getattr(self, name)
            if value is not None and not isinstance(value, str):
                raise TypeError(f"{name} must be a string or None")
            if isinstance(value, str) and not value.strip():
                raise ValueError(f"{name} must be non-empty when provided")
        for name in ("original", "counterfactual"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, TemporalExample):
                raise TypeError(f"{name} must be a TemporalExample or None")

        extraction = self.extraction_result.extraction
        extraction_rejection = self.extraction_result.rejection
        reliable = extraction is not None and is_reliable_relation(extraction)
        successful_rewrite = isinstance(self.rewrite_result, CounterfactualRewrite)
        rejected_rewrite = isinstance(self.rewrite_result, ExtractionResult)

        if self.terminal is ConstructionTerminal.NO_MARKER:
            valid_terminal = (
                extraction_rejection is not None
                and extraction_rejection.reason is RejectionReason.NO_MARKER
            )
            expected_outcome = ConstructionOutcome()
        elif self.terminal is ConstructionTerminal.EXTRACTION_REJECTED:
            valid_terminal = (
                extraction_rejection is not None
                and extraction_rejection.reason is not RejectionReason.NO_MARKER
            ) or (extraction is not None and not reliable)
            expected_outcome = (
                ConstructionOutcome(True, True)
                if extraction is not None
                else ConstructionOutcome(True)
            )
        elif self.terminal is ConstructionTerminal.TEXT_QUESTION_ALIAS_UNSUPPORTED:
            valid_terminal = reliable
            expected_outcome = ConstructionOutcome(True, True, True)
        elif self.terminal is ConstructionTerminal.REWRITE_REJECTED:
            valid_terminal = reliable and rejected_rewrite and not self.rewrite_result.accepted
            expected_outcome = ConstructionOutcome(True, True, True)
        elif self.terminal is ConstructionTerminal.MULTIPLE_ANSWERS_UNSUPPORTED:
            valid_terminal = reliable and successful_rewrite
            expected_outcome = ConstructionOutcome(True, True, True, True)
        elif self.terminal is ConstructionTerminal.ANSWER_UPDATE_UNKNOWN:
            valid_terminal = (
                reliable
                and successful_rewrite
                and self.answer_update is not None
                and self.answer_update.status is AnswerStatus.UNKNOWN
            )
            expected_outcome = ConstructionOutcome(True, True, True, True)
        else:
            valid_terminal = (
                reliable
                and successful_rewrite
                and self.answer_update is not None
                and self.answer_update.status is AnswerStatus.KNOWN
            )
            expected_outcome = ConstructionOutcome(True, True, True, True, True)

        if not valid_terminal:
            raise ValueError("terminal is inconsistent with its construction evidence")
        if self.outcome != expected_outcome:
            raise ValueError("outcome is inconsistent with terminal")

        rewrite_expected = self.terminal in {
            ConstructionTerminal.REWRITE_REJECTED,
            ConstructionTerminal.MULTIPLE_ANSWERS_UNSUPPORTED,
            ConstructionTerminal.ANSWER_UPDATE_UNKNOWN,
            ConstructionTerminal.RETAINED,
        }
        if (self.rewrite_result is not None) != rewrite_expected:
            raise ValueError("rewrite_result presence is inconsistent with terminal")

        update_expected = self.terminal in {
            ConstructionTerminal.ANSWER_UPDATE_UNKNOWN,
            ConstructionTerminal.RETAINED,
        }
        if (self.answer_update is not None) != update_expected:
            raise ValueError("answer_update presence is inconsistent with terminal")

        identities = (
            self.template_id,
            self.prospective_pair_id,
            self.prospective_counterfactual_record_id,
        )
        identities_expected = self.terminal in {
            ConstructionTerminal.MULTIPLE_ANSWERS_UNSUPPORTED,
            ConstructionTerminal.ANSWER_UPDATE_UNKNOWN,
            ConstructionTerminal.RETAINED,
        }
        if any(value is not None for value in identities) != identities_expected:
            raise ValueError("prospective identity presence is inconsistent with terminal")
        if identities_expected and any(value is None for value in identities):
            raise ValueError("all prospective identities are required after rewrite success")
        if successful_rewrite and self.template_id != self.rewrite_result.template_id:
            raise ValueError("template_id does not match rewrite_result")

        finals_present = self.original is not None and self.counterfactual is not None
        if (self.original is None) != (self.counterfactual is None):
            raise ValueError("final original and counterfactual must be present together")
        if finals_present != (self.terminal is ConstructionTerminal.RETAINED):
            raise ValueError("final pair presence is inconsistent with terminal")
        if finals_present:
            assert extraction is not None
            assert isinstance(self.rewrite_result, CounterfactualRewrite)
            assert self.answer_update is not None
            assert self.answer_update.value is not None
            assert self.prospective_pair_id is not None
            assert self.prospective_counterfactual_record_id is not None
            assert self.original is not None
            assert self.counterfactual is not None
            self._validate_final_pair(extraction, self.rewrite_result)

    def _validate_final_pair(
        self, extraction: Extraction, rewrite: CounterfactualRewrite
    ) -> None:
        assert self.original is not None
        assert self.counterfactual is not None
        assert self.answer_update is not None
        assert self.prospective_pair_id is not None
        assert self.prospective_counterfactual_record_id is not None
        original = self.original
        counterfactual = self.counterfactual

        if original.record_id != self.input_record_id:
            raise ValueError("final original record ID changed")
        if counterfactual.record_id != self.prospective_counterfactual_record_id:
            raise ValueError("counterfactual record ID is not the prospective ID")
        if (
            original.counterfactual_pair_id != self.prospective_pair_id
            or counterfactual.counterfactual_pair_id != self.prospective_pair_id
        ):
            raise ValueError("final records do not share the prospective pair ID")
        shared_fields = (
            "source_id",
            "dataset",
            "split",
            "revision",
            "source_sha256",
            "question",
            "answer_type",
        )
        if any(getattr(original, name) != getattr(counterfactual, name) for name in shared_fields):
            raise ValueError("final records do not preserve shared source fields")
        if original.text != extraction.text or original.text != rewrite.original_text:
            raise ValueError("final original text does not match extraction")
        if counterfactual.text != rewrite.rewritten_text:
            raise ValueError("final counterfactual text does not match rewrite")
        if original.events != (extraction.event_a, extraction.event_b):
            raise ValueError("final original events do not match extraction")
        if original.relations != (extraction.relation,):
            raise ValueError("final original relation does not match extraction")
        if counterfactual.events != (rewrite.rewritten.event_a, rewrite.rewritten.event_b):
            raise ValueError("final counterfactual events do not match rewrite")
        if counterfactual.relations != (rewrite.rewritten.relation,):
            raise ValueError("final counterfactual relation does not match rewrite")
        if counterfactual.answers != (self.answer_update.value,):
            raise ValueError("counterfactual answer does not match answer update")


def is_reliable_relation(extraction: Extraction) -> bool:
    if not isinstance(extraction, Extraction):
        raise TypeError("extraction must be an Extraction")
    return extraction.relation.relation is not Relation.UNKNOWN


def _prospective_ids(
    original: TemporalExample, rewrite: CounterfactualRewrite
) -> tuple[str, str]:
    pair_id = make_stable_id(
        "counterfactual-pair",
        {
            "version": "explicit-marker-construction-v0",
            "source_id": original.source_id,
            "original_record_id": original.record_id,
            "template_id": rewrite.template_id,
        },
    )
    counterfactual_record_id = make_stable_id(
        "record",
        {
            "version": "counterfactual-explicit-marker-v0",
            "source_id": original.source_id,
            "original_record_id": original.record_id,
            "counterfactual_pair_id": pair_id,
            "template_id": rewrite.template_id,
            "variant": "counterfactual",
        },
    )
    return pair_id, counterfactual_record_id


def construct_explicit_counterfactual(original: TemporalExample) -> ConstructionResult:
    if not isinstance(original, TemporalExample):
        raise TypeError("original must be a TemporalExample")
    if original.events != ():
        raise ValueError("original events must be empty")
    if original.relations != ():
        raise ValueError("original relations must be empty")
    if original.counterfactual_pair_id is not None:
        raise ValueError("original counterfactual_pair_id must be None")

    extraction_result = extract_explicit_relation(original.text)
    if not extraction_result.accepted:
        assert extraction_result.rejection is not None
        no_marker = extraction_result.rejection.reason is RejectionReason.NO_MARKER
        return ConstructionResult(
            original.record_id,
            ConstructionOutcome() if no_marker else ConstructionOutcome(True),
            ConstructionTerminal.NO_MARKER if no_marker else ConstructionTerminal.EXTRACTION_REJECTED,
            extraction_result,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
        )

    extraction = extraction_result.extraction
    assert extraction is not None
    if not is_reliable_relation(extraction):
        return ConstructionResult(
            original.record_id,
            ConstructionOutcome(True, True),
            ConstructionTerminal.EXTRACTION_REJECTED,
            extraction_result,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
        )

    if original.text == original.question:
        return ConstructionResult(
            original.record_id,
            ConstructionOutcome(True, True, True),
            ConstructionTerminal.TEXT_QUESTION_ALIAS_UNSUPPORTED,
            extraction_result,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
        )

    rewrite_result = rewrite_counterfactual(extraction)
    if isinstance(rewrite_result, ExtractionResult):
        return ConstructionResult(
            original.record_id,
            ConstructionOutcome(True, True, True),
            ConstructionTerminal.REWRITE_REJECTED,
            extraction_result,
            rewrite_result,
            None,
            None,
            None,
            None,
            None,
            None,
        )

    pair_id, counterfactual_record_id = _prospective_ids(original, rewrite_result)
    if len(original.answers) != 1:
        return ConstructionResult(
            original.record_id,
            ConstructionOutcome(True, True, True, True),
            ConstructionTerminal.MULTIPLE_ANSWERS_UNSUPPORTED,
            extraction_result,
            rewrite_result,
            None,
            rewrite_result.template_id,
            pair_id,
            counterfactual_record_id,
            None,
            None,
        )

    answer_update = update_answer(
        question=original.question,
        original_answer=original.answers[0],
        answer_type=original.answer_type,
        rewrite=rewrite_result,
    )
    if answer_update.status is AnswerStatus.UNKNOWN:
        return ConstructionResult(
            original.record_id,
            ConstructionOutcome(True, True, True, True),
            ConstructionTerminal.ANSWER_UPDATE_UNKNOWN,
            extraction_result,
            rewrite_result,
            answer_update,
            rewrite_result.template_id,
            pair_id,
            counterfactual_record_id,
            None,
            None,
        )

    final_original = replace(
        original,
        events=(extraction.event_a, extraction.event_b),
        relations=(extraction.relation,),
        counterfactual_pair_id=pair_id,
    )
    rewritten = rewrite_result.rewritten
    final_counterfactual = TemporalExample(
        record_id=counterfactual_record_id,
        source_id=original.source_id,
        dataset=original.dataset,
        split=original.split,
        revision=original.revision,
        source_sha256=original.source_sha256,
        text=rewrite_result.rewritten_text,
        question=original.question,
        answers=(answer_update.value,),
        answer_type=original.answer_type,
        events=(rewritten.event_a, rewritten.event_b),
        relations=(rewritten.relation,),
        counterfactual_pair_id=pair_id,
    )
    return ConstructionResult(
        original.record_id,
        ConstructionOutcome(True, True, True, True, True),
        ConstructionTerminal.RETAINED,
        extraction_result,
        rewrite_result,
        answer_update,
        rewrite_result.template_id,
        pair_id,
        counterfactual_record_id,
        final_original,
        final_counterfactual,
    )
