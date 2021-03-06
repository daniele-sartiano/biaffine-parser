# -*- coding: utf-8 -*-

from collections import Counter
from parser.utils.fn import pad
from parser.utils.vocab import Vocab

import torch
import sys

class RawField(object):

    def __init__(self, name, fn=None):
        super(RawField, self).__init__()

        self.name = name
        self.fn = fn

    def __repr__(self):
        return f"({self.name}): {self.__class__.__name__}()"

    def preprocess(self, sequence):
        if self.fn is not None:
            sequence = self.fn(sequence)
        return sequence

    def transform(self, sequences):
        return [self.preprocess(seq) for seq in sequences]


class Field(RawField):

    def __init__(self, name, pad=None, unk=None, bos=None, eos=None,
                 lower=False, use_vocab=True, tokenize=None, fn=None):
        self.name = name
        self.pad = pad
        self.unk = unk
        self.bos = bos
        self.eos = eos
        self.lower = lower
        self.use_vocab = use_vocab
        self.tokenize = tokenize
        self.fn = fn
        self.mask_token_id = 0

        self.specials = [token for token in [pad, unk, bos, eos]
                         if token is not None]

    def __repr__(self):
        s, params = f"({self.name}): {self.__class__.__name__}(", []
        if self.pad is not None:
            params.append(f"pad={self.pad}")
        if self.unk is not None:
            params.append(f"unk={self.unk}")
        if self.bos is not None:
            params.append(f"bos={self.bos}")
        if self.eos is not None:
            params.append(f"eos={self.eos}")
        if self.lower:
            params.append(f"lower={self.lower}")
        if not self.use_vocab:
            params.append(f"use_vocab={self.use_vocab}")
        s += ", ".join(params)
        s += ")"

        return s

    @property
    def pad_index(self):
        if self.pad is None:
            return 0
        if hasattr(self, 'vocab'):
            return self.vocab[self.pad]
        return self.specials.index(self.pad)

    @property
    def unk_index(self):
        if self.unk is None:
            return 0
        if hasattr(self, 'vocab'):
            return self.vocab[self.unk]
        return self.specials.index(self.unk)

    @property
    def bos_index(self):
        if hasattr(self, 'vocab'):
            return self.vocab[self.bos] if self.bos else 0
        return self.specials.index(self.bos) if self.bos else 0

    @property
    def eos_index(self):
        if hasattr(self, 'vocab'):
            return self.vocab[self.eos] if self.eos else 0
        return self.specials.index(self.eos) if self.eos else 0

    def preprocess(self, sequence):
        if self.fn is not None:
            sequence = self.fn(sequence)
        if self.tokenize is not None:
            sequence = self.tokenize(sequence)
        if self.lower:
            sequence = [str.lower(token) for token in sequence]

        return sequence

    def build(self, corpus, min_freq=1, embed=None):
        if hasattr(self, 'vocab'):
            return
        sequences = getattr(corpus, self.name)
        counter = Counter(token
                          for seq in sequences
                          for token in self.preprocess(seq))
        self.vocab = Vocab(counter, min_freq, self.specials, self.unk_index)

        if not embed:
            self.embed = None
        else:
            tokens = self.preprocess(embed.tokens)
            # if the `unk` token has existed in the pretrained,
            # then replace it with a self-defined one
            if embed.unk:
                tokens[embed.unk_index] = self.unk

            self.vocab.extend(tokens)
            self.embed = torch.zeros(len(self.vocab), embed.dim)
            self.embed[self.vocab[tokens]] = embed.vectors
            self.embed /= torch.std(self.embed)

    def transform(self, sequences):
        sequences = [self.preprocess(seq) for seq in sequences]
        if self.use_vocab:
            sequences = [self.vocab[seq] for seq in sequences]
        if self.bos:
            sequences = [[self.bos_index] + seq for seq in sequences]
        if self.eos:
            sequences = [seq + [self.eos_index] for seq in sequences]
        sequences = [torch.tensor(seq) for seq in sequences]

        return sequences


class SubwordField(Field):

    def __init__(self, *args, **kwargs):
        tokenizer = kwargs.pop('tokenizer') if 'tokenizer' in kwargs else 0
        self.fix_len = kwargs.pop('fix_len') if 'fix_len' in kwargs else 0
        super(SubwordField, self).__init__(*args, **kwargs)
        self.pad = tokenizer.pad_token
        self.unk = tokenizer.unk_token
        self.bos = tokenizer.bos_token or tokenizer.cls_token
        self.mask_token_id = tokenizer.mask_token_id
        self.tokenize = tokenize=tokenizer.tokenize

    def build(self, corpus, min_freq=1, embed=None):
        if hasattr(self, 'vocab'):
            return
        sequences = getattr(corpus, self.name)
        counter = Counter(piece
                          for seq in sequences
                          for token in seq
                          for piece in self.preprocess(token))
        self.vocab = Vocab(counter, min_freq, self.specials, self.unk_index)

        if not embed:
            self.embed = None
        else:
            tokens = self.preprocess(embed.tokens)
            # if the `unk` token has existed in the pretrained,
            # then replace it with a self-defined one
            if embed.unk:
                tokens[embed.unk_index] = self.unk

            self.vocab.extend(tokens)
            self.embed = torch.zeros(len(self.vocab), embed.dim)
            self.embed[self.vocab[tokens]] = embed.vectors

    def transform(self, sequences):
        sequences = [[self.preprocess(token) for token in seq]
                     for seq in sequences]
        if self.fix_len <= 0:
            self.fix_len = max(len(token)
                               for seq in sequences
                               for token in seq)
        if self.use_vocab:
            sequences = [[[self.vocab[i] for i in token] for token in seq]
                         for seq in sequences]
        if self.bos:
            sequences = [[[self.bos_index]] + seq for seq in sequences]
        if self.eos:
            sequences = [seq + [[self.eos_index]] for seq in sequences]
        lens = [min(self.fix_len, max(len(ids) for ids in seq)) for seq in sequences]
        sequences = [pad([torch.tensor(ids[:i]) for ids in seq], self.pad_index, i)
                     for i, seq in zip(lens, sequences)]

        return sequences

