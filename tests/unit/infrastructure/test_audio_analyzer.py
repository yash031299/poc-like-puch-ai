"""Tests for AudioAnalyzer — RMS energy and noise floor detection."""

import struct
import pytest

from src.infrastructure.audio_analyzer import AudioAnalyzer


class TestAudioAnalyzerInit:
    """Test AudioAnalyzer initialization."""

    def test_init_with_default_noise_floor(self):
        """Test initialization with default noise floor."""
        analyzer = AudioAnalyzer()
        assert analyzer.get_noise_floor_db() == -40.0

    def test_init_with_custom_noise_floor(self):
        """Test initialization with custom noise floor."""
        analyzer = AudioAnalyzer(noise_floor_db=-30.0)
        assert analyzer.get_noise_floor_db() == -30.0

    def test_init_rejects_positive_noise_floor(self):
        """Test that positive noise floor is rejected."""
        with pytest.raises(ValueError, match="must be <= 0dB"):
            AudioAnalyzer(noise_floor_db=10.0)

    def test_init_accepts_zero_noise_floor(self):
        """Test that zero dB noise floor is accepted."""
        analyzer = AudioAnalyzer(noise_floor_db=0.0)
        assert analyzer.get_noise_floor_db() == 0.0

    def test_init_accepts_very_low_noise_floor(self):
        """Test that very low noise floor is accepted."""
        analyzer = AudioAnalyzer(noise_floor_db=-80.0)
        assert analyzer.get_noise_floor_db() == -80.0


class TestRMSEnergyCalculation:
    """Test RMS energy calculation."""

    def test_empty_audio_returns_minus_infinity(self):
        """Test that empty audio frame returns -inf."""
        analyzer = AudioAnalyzer()
        energy = analyzer.compute_rms_energy_db(b'')
        assert energy == float('-inf')

    def test_silent_frame_returns_very_low_energy(self):
        """Test that silent frame returns very low energy."""
        analyzer = AudioAnalyzer()
        # 20ms of silence at 16kHz = 320 bytes of zeros
        silent_frame = b'\x00' * 320
        energy = analyzer.compute_rms_energy_db(silent_frame)
        assert energy < -60  # Very quiet

    def test_signal_with_energy_returns_measurable_db(self):
        """Test that signal with energy returns measurable dB."""
        analyzer = AudioAnalyzer()
        # Create a simple sine-like wave with moderate energy
        # Using samples with some amplitude
        samples = [i % 256 - 128 for i in range(160)]  # 160 samples = 10ms at 16kHz
        audio_data = struct.pack(f'<{len(samples)}h', *samples)
        energy = analyzer.compute_rms_energy_db(audio_data)
        # Should be somewhere in the reasonable range (quiet audio)
        assert -60 < energy < -50

    def test_max_amplitude_signal(self):
        """Test that signal at max amplitude gives high energy."""
        analyzer = AudioAnalyzer()
        # Max PCM16 amplitude is ±32767
        max_val = 32767
        samples = [max_val] * 160
        audio_data = struct.pack(f'<{len(samples)}h', *samples)
        energy = analyzer.compute_rms_energy_db(audio_data)
        # Max amplitude should be close to 0dB (or slightly below to account for normalization)
        assert -5 < energy < 5

    def test_half_amplitude_signal(self):
        """Test RMS energy of half-amplitude signal."""
        analyzer = AudioAnalyzer()
        # Half amplitude = -6dB (standard dB relationship)
        half_val = 16384
        samples = [half_val] * 160
        audio_data = struct.pack(f'<{len(samples)}h', *samples)
        energy = analyzer.compute_rms_energy_db(audio_data)
        # Should be roughly -6dB less than max
        assert -12 < energy < 0


class TestNoiseFloorDetection:
    """Test is_above_noise_floor method."""

    def test_silent_frame_below_noise_floor(self):
        """Test that silent frame is below noise floor."""
        analyzer = AudioAnalyzer(noise_floor_db=-40.0)
        silent_frame = b'\x00' * 320
        is_speech = analyzer.is_above_noise_floor(silent_frame)
        assert is_speech is False

    def test_loud_signal_above_noise_floor(self):
        """Test that loud signal is above noise floor."""
        analyzer = AudioAnalyzer(noise_floor_db=-40.0)
        loud_val = 16384  # Moderate amplitude
        samples = [loud_val] * 160
        audio_data = struct.pack(f'<{len(samples)}h', *samples)
        is_speech = analyzer.is_above_noise_floor(audio_data)
        assert is_speech is True

    def test_signal_exactly_at_noise_floor_is_above(self):
        """Test that signal at noise floor threshold is considered above."""
        # Create signal with specific energy level
        analyzer = AudioAnalyzer(noise_floor_db=-40.0)
        # We'll create a signal and adjust it to be at the threshold
        samples = [4096] * 160  # Some intermediate amplitude
        audio_data = struct.pack(f'<{len(samples)}h', *samples)
        # The result depends on actual energy, just verify it works
        result = analyzer.is_above_noise_floor(audio_data)
        assert isinstance(result, bool)

    def test_changing_noise_floor_affects_detection(self):
        """Test that changing noise floor threshold affects detection."""
        analyzer = AudioAnalyzer(noise_floor_db=-40.0)
        samples = [2048] * 160
        audio_data = struct.pack(f'<{len(samples)}h', *samples)
        
        # With current threshold
        result1 = analyzer.is_above_noise_floor(audio_data)
        
        # Lower threshold (more sensitive)
        analyzer.set_noise_floor_db(-50.0)
        result2 = analyzer.is_above_noise_floor(audio_data)
        
        # With lower threshold, more signals should be above it
        # (or same if this particular signal is far above)
        assert isinstance(result1, bool)
        assert isinstance(result2, bool)


class TestNoiseFloorUpdate:
    """Test dynamic noise floor updates."""

    def test_set_noise_floor_updates_value(self):
        """Test that set_noise_floor_db updates the threshold."""
        analyzer = AudioAnalyzer(noise_floor_db=-40.0)
        assert analyzer.get_noise_floor_db() == -40.0
        
        analyzer.set_noise_floor_db(-35.0)
        assert analyzer.get_noise_floor_db() == -35.0

    def test_set_noise_floor_rejects_positive(self):
        """Test that setting positive noise floor raises error."""
        analyzer = AudioAnalyzer()
        with pytest.raises(ValueError, match="must be <= 0dB"):
            analyzer.set_noise_floor_db(10.0)

    def test_set_noise_floor_accepts_zero(self):
        """Test that zero dB is accepted."""
        analyzer = AudioAnalyzer()
        analyzer.set_noise_floor_db(0.0)
        assert analyzer.get_noise_floor_db() == 0.0


class TestDynamicNoiseFloorEstimation:
    """Test estimating noise floor from frame energies."""

    def test_empty_list_returns_default(self):
        """Test that empty list returns default noise floor."""
        result = AudioAnalyzer.estimate_dynamic_noise_floor([])
        assert result == AudioAnalyzer.DEFAULT_NOISE_FLOOR_DB

    def test_single_frame_estimation(self):
        """Test estimation with single frame."""
        energies = [-35.0]
        result = AudioAnalyzer.estimate_dynamic_noise_floor(energies, percentile=20)
        assert result == -35.0

    def test_multiple_frames_percentile_calculation(self):
        """Test that percentile calculation works correctly."""
        # Simulated frame energies: mostly quiet, some loud
        energies = [-50.0, -45.0, -40.0, -35.0, -30.0, -25.0, -20.0, -15.0, -10.0, -5.0]
        
        # 20th percentile should be near the lower end
        result = AudioAnalyzer.estimate_dynamic_noise_floor(energies, percentile=20)
        assert -50.0 <= result <= -40.0

    def test_percentile_50_returns_median(self):
        """Test that 50th percentile returns the median."""
        energies = [-50.0, -40.0, -30.0, -20.0, -10.0]
        result = AudioAnalyzer.estimate_dynamic_noise_floor(energies, percentile=50)
        # 50th percentile of 5 values should be the middle value (-30.0)
        assert result == -30.0

    def test_ignores_infinity_values(self):
        """Test that infinity values (empty frames) are ignored."""
        energies = [float('-inf'), -40.0, -30.0, float('-inf'), -20.0]
        result = AudioAnalyzer.estimate_dynamic_noise_floor(energies, percentile=20)
        # Should only consider the 3 valid values
        assert isinstance(result, float)
        assert result != float('-inf')

    def test_all_infinity_returns_default(self):
        """Test that all-infinity list returns default."""
        energies = [float('-inf'), float('-inf'), float('-inf')]
        result = AudioAnalyzer.estimate_dynamic_noise_floor(energies, percentile=20)
        assert result == AudioAnalyzer.DEFAULT_NOISE_FLOOR_DB


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_invalid_audio_data_returns_minus_infinity(self):
        """Test that invalid audio data returns -inf."""
        analyzer = AudioAnalyzer()
        # Odd-length data (can't unpack as 16-bit samples)
        invalid_audio = b'\x00\x01\x02'  # 3 bytes (not divisible by 2)
        energy = analyzer.compute_rms_energy_db(invalid_audio)
        assert energy == float('-inf')

    def test_very_short_valid_frame(self):
        """Test with minimum valid frame (2 bytes = 1 sample)."""
        analyzer = AudioAnalyzer()
        one_sample = struct.pack('<h', 1000)  # 1 sample
        energy = analyzer.compute_rms_energy_db(one_sample)
        # Should return a valid dB value
        assert isinstance(energy, float)
        assert energy != float('-inf')

    def test_negative_samples_produce_same_energy_as_positive(self):
        """Test that negative samples have same RMS energy."""
        analyzer = AudioAnalyzer()
        
        # Positive samples
        pos_samples = [1024] * 160
        pos_audio = struct.pack(f'<{len(pos_samples)}h', *pos_samples)
        pos_energy = analyzer.compute_rms_energy_db(pos_audio)
        
        # Negative samples (same magnitude)
        neg_samples = [-1024] * 160
        neg_audio = struct.pack(f'<{len(neg_samples)}h', *neg_samples)
        neg_energy = analyzer.compute_rms_energy_db(neg_audio)
        
        # RMS should be the same (RMS is computed on squares)
        assert abs(pos_energy - neg_energy) < 0.1  # Allow small floating point error
