import find_peaks as peaks
import numpy as np
import matplotlib.pyplot as plt
import collections
import scikits.audiolab
import processing as p
import utility as u
import os
import mutagen.mp3
from call_handler import CallHandler

def verify_call(call):
    """
    """
    print "Before: call {}, verified? {}".format(call, call.verified)
    parser = Parser(call.filename, None, call.offset, step_size_divisor=64)
    response = parser.verify_call(call)
    print "Response: {}".format(response)
    if response == True:
        call.verified = True
        call.save()
    elif response == False:
        call.verified = False
        call.save()
    elif response == "q":
        return False
    print "After: call {}, verified? {}".format(call, call.verified)
    return True

def parse_mp3(mp3file, handler):
    info = mutagen.mp3.MP3(mp3file).info
    total = 0
    has_count = False
    #if info.length > 3600:
    ##TODO I think any reasonable lengthed file can be handled now, but not certain until 
    ##I verify through testing
        #raise Exception("File ({}) too long for code to handle - " \
                #"currently setup to only handle files of less than " \
                #"60 minutes.  This file is {:.2f} minutes".format(mp3file,
                    #info.length/60))
        #Limiting to 1 hour here because larger files should be split
        #up differently since even at an hour this will create around
        #600 MB of wav files.  TODO deal with larger files in a 
        #sensible manner and probably delete the wav file segments
        #after use.  For now I will leave it like this though since
        #the wav files will probably be useful for debugging purposes
    for audio, offset in p.segment_mp3(mp3file, 600):
        print "parsing {} at offset {}".format(os.path.basename(audio), offset)
        parser = Parser(audio, handler, offset)
        parser.identify_calls()
        try:
            total += handler.count
            has_count = True
        except AttributeError:
            pass
        parser.close()
    if has_count:
        print "Total count: {}".format(total)


class Parser(object):
    """
    This class is for taking an audio file and parsing it to identify pika
    calls.  It should be passed an object of type CallHandler to deal with
    the output of identified calls as they are found.
    
    Long sections of audio are tough on memory usage, so longer audio is
    pre-chopped into 10 second or shorter chunks.  This can cause issues if
    a pika call is on a bounder between chunks.  If necessary the code could
    be adjusted to deal with that situation, but for now it will be ignored
    in favor of getting things working otherwise.
    """
    #*Constructor*#
    def __init__(self, audio_file, handler, offset=0, step_size_divisor=2, debug=False):
        """
        :audio_file should be the path to a wav file.
        :handler should be of type CallHandler
        :offset for if file is a segment of a parent audio file, for
        example if it starts at 240 seconds into the original file the
        offset should be 240
        """
        print audio_file

        self.offset = offset

        self.full_audio, self.frequency = self.load_audio(audio_file)

        if not isinstance(handler, CallHandler) and handler is not None:
            raise Exception("pika.Parser called with handler that is not " \
                    "an instance of CallHandler: {}".format(handler))
        else:
            self.handler = handler
        if int(self.frequency) != 44100:
            raise Exception("pika.Parser: loaded file ({}) with frequency {}." \
                    "  Frequency should be 44100.".format(audio_file, frequency))
        self.debug = debug
        
        self.fft = None
        self.fft_size = 4096
        self.step_size = int(self.fft_size*1.0/step_size_divisor)
        self.factor = self.step_size*1.0/self.frequency
        self.fft_window = [self.fft_size/32 + 150]
        self.fft_window.append(self.fft_window[0] + 275)
        
        #minimum peak distance for calculating harmonic frequencies
        self.mpd = 40 
        
        #each ipd must fall within one of the ipd_filter ranges to be 
        #considered a successful candidate for a pika call
        
        #tuned for beacon rock
        #self.ipd_filters = [[52, 70], [110, 135]] 
        #self.base_peak_filter = [30, 60]
    
        #tuned for angel's rest
        #self.ipd_filters = [[60, 93], [130, 165]] 
        #self.base_peak_filter = [30, 60]
        
        #tuned for Herman's Creek
        #self.ipd_filters = [[45, 80], [130, 165]] 
        #self.base_peak_filter = [15, 60]
        
        #joint tuning
        self.ipd_filters = [[45, 93], [110, 165]] 
        self.base_peak_filter = [15, 60]
        
        self.interval_finder=self.interval_finder_with_negative

    def close(self):
        """Handles needed cleanup in particular sets full_audio to None
        """
        self.full_audio = None
    
    def analyze_interval(self, interval, nice_plotting=False, title=None):
        """Displays spectrogram and some related data for given time interval 
        in the loaded audio.
        :interval list of form [start, end] in seconds
        """
        self.debug = True
        if nice_plotting:
            self.step_size = int(self.fft_size*1.0/64) #/64
            self.factor = self.step_size*1.0/self.frequency
        else:
            self.step_size = int(self.fft_size*1.0/2) #/64
            self.factor = self.step_size*1.0/self.frequency

        audio = self.get_audio_interval(interval)
        self.filtered_fft(audio)
        frame_scores = self.score_fft(with_negative=True)
        print "Passing intervals {}".format(
                self.find_passing_intervals(frame_scores))
        self.spectrogram(title=title)
        self.debug = False
    
    def get_audio_interval(self, interval):
        return self.full_audio[int(interval[0]*self.frequency):
                int(interval[1]*self.frequency)]

    def basic_interval_finder(self):
        """Returns set of passing intervals (in seconds) when fft is run through
        the base scoring function.
        """
        frame_scores = self.score_fft()
        return self.find_passing_intervals(frame_scores)
    
    def interval_finder_with_negative(self):
        frame_scores = self.score_fft(with_negative=True)
        return self.find_passing_intervals(frame_scores)

    
    def identify_calls(self):
    #, interval_finder=None, base_offset=0.0):
        #"""
        #:interval_finder should be a function that accepts an fft and returns
        #a list of intervals (which should each be a list of the form [start, end]
        #in seconds)
        #:base_offset is the offset of the audio being analyzed if it part of a 
        #larger audio file
        #"""
        #if interval_finder is None:
        #self.basic_interval_finder
        if self.debug:
            print "ipd filters: {}".format(self.ipd_filters)
        with self.handler as handler:
            for chunk, offset in p.segment_audio(self.full_audio, self.frequency):
                self.filtered_fft(chunk)
                good_intervals = self.interval_finder()
                for interval in good_intervals:
                    handler.handle_call(self.offset + offset + interval[0],
                            self.full_audio[int((offset + interval[0])*self.frequency):
                                int((offset + interval[1])*self.frequency)])

    def verify_call(self, call):
        plt.ion()
        self.filtered_fft(self.full_audio)
        self.spectrogram("call id: {}, offset {:.0f}:{:2.1f}".format(call.id, 
            np.floor(call.offset/60), call.offset%60))
        response = u.get_verification(call)
        plt.close()
        return response

    #*Private Methods*#
    def load_audio(self, audio_file):
        if audio_file[-3:] == "mp3":
            raise Exception("pika.Parser only works directly on wav files" \
                    "to process mp3, use pika.parse_mp3 helper function." )
        elif audio_file[-3:] == "wav":
            (audio, frequency, nBits) = scikits.audiolab.wavread(audio_file)
            if audio.ndim == 2: 
                #get left channel if a stereo file not needed for mono
                audio = [v[0] for v in audio]
        return audio, frequency
    
    def filtered_fft(self, audio=None):
        if audio is None:
            audio = self.full_audio
        first_dim=np.ceil(1.0*(len(audio))/(self.step_size))
        second_dim = self.fft_window[1] - self.fft_window[0]
        fft = np.zeros((first_dim, second_dim))
        for i in xrange(0, len(audio), self.step_size):
            f = np.absolute(np.fft.fft(audio[i:i+self.fft_size], self.fft_size))
            f = f[self.fft_window[0]:self.fft_window[1]] 
            fft[i/self.step_size] = f 
        
        #normalize
        max_val = np.amax(fft)
        fft = fft/np.max([max_val, .1])
        if self.debug:
            print "segment max value: {}".format(max_val)
        
        #noise-reduction
        avg_fft = np.sum(fft, axis=0)/len(fft)
        for i, frame in enumerate(fft):
            fft[i] = [max(frame[j]-avg_fft[j], 0) for j, v in enumerate(frame)] 
        
        #filter out quiet parts
        f_mean = np.mean(fft)
        threshold = .05
        #self.fft = [[1 if x > .08 else x for x in f] for f in fft] 
        #self.fft = [[10*x if x <= .1 and x > .01 else x for x in f] for f in fft] 
        self.fft = [[x if x > f_mean + threshold else 0.0 for x in f] for f in fft] 
    
    def fft_bin_to_frequency(self, bin_number):
        """self.step_size, self.frequency, and self.fft_window all need to be 
        defined for this to work correctly.
        :bin_number: which bin we want to know the frequency of, should be relative
        to the fft_window.  E.g. bin_number = 50 would be bin self.fft_window[0] + 50
        from the original unfiltered/windowed fft.
        :returns to the bottom frequency corresponding to bin_number
        """
        #bin size is the frequency band encompassed by each bin
        bin_size = 1.0*self.frequency/self.fft_size
        return (1+bin_number+self.fft_window[0])*bin_size
    
    def score_fft(self, with_negative=False):
        """Scores frames for how likely they seem to be part of a pika call
        :debug: if True outputs statements to help debug scoring process
        :returns 1d array of likeliness scores corresponding to the frames
        """
        scores = []
        running_score = 0
        n_scores = collections.deque([])
        keep_n = 3
        amount = 0
        for i, frame in enumerate(self.fft):
            perc_85 = np.percentile(frame, 85)
            frame_max = np.max(frame)
            score = 0.0
            count = 0
            if True or (frame_max > 0 and perc_85/frame_max > .05):
                locs = peaks.detect_peaks(frame, mpd=self.mpd)
                
                #tuned for beacon rock
                #if len(locs) >= 3 and locs[0] < 90: 
                
                #tuned for angel's rest
                #if len(locs) >= 3 and locs[0] < 120 and locs[0] > 25: 
                
                #tuned for Herman's Creek
                #if len(locs) >= 3 and locs[0] < 120: 
                #having trouble with noise in Herman's Creek -maybe can look at
                #filter on peak energy vs. trough per frame or perhaps on total
                #energy per frame since I suspect the pika calls have overall 
                #higher intensity than the noisy bits

                #joint tuning
                if len(locs) >= 3 and locs[0] < 120:
                    ipd = np.convolve(locs, [1, -1])
                    amount = 5.0/(len(locs) - 2)
                    if ((ipd[0] >= self.base_peak_filter[0]) and
                            (ipd[0] <= self.base_peak_filter[1])):
                        score += amount
                    else:
                        score -= amount/2

                    for x in ipd[1:-1]:
                        if any((x >= bot) and (x <= top) 
                                for bot, top in self.ipd_filters):
                            score += amount
                            count += 1
                        elif with_negative:
                            score -= amount/2
                else:
                    score -= 1
                if len(n_scores) == keep_n:
                    running_score -= n_scores.popleft()
                n_scores.append(score)
                running_score += score

                if self.debug:
                    if len(locs) != 0:
                        ipd = np.convolve(locs, [1, -1])
                        print "t: {:.2f}, {:.1f} | {} | ipd {}, count {}, score {}".format(i*self.factor, running_score, amount, ipd, count, score)
                        r_max = np.max(frame)
                        print "t: {:.2f}, 85%: {:.3f}, mean: {:.3f}, sd: {:.3f}".format(
                                i*self.factor, np.percentile(frame, 85)/r_max,
                                np.mean(frame)/r_max, np.std(frame)/r_max)
                        print "t: {:.2f}, f: {}, ipd sd: {:.1f}, mean: {:.1f}, frame max: {:.3f}".format(
                                i*self.factor, i,
                                np.std(ipd[1:-1]), np.mean(ipd[1:-1]), frame_max)

            scores.append(score)
        return scores
    
    def find_passing_intervals(self, frame_scores):
        """
        :frame_scores: pika call likelihood scores of fft frames.
        :returns list of intervals (in seconds) that are identified as 
        containing a pika call
        """
        if self.factor > .05:
            scores = np.convolve(frame_scores,
                    [.5, .5, .5], mode='same')
        else:
            scores = np.convolve(frame_scores,
                    [.5, .5, .5, .5, .5, .5, .5, .5, .5, .5], mode='same')
        #if self.debug:
            #print "frame_scores: {}".format(frame_scores)
            #print "smoothed scores: {}".format(scores)
        ridges = []
        current_ridge = None
        #threshold = 10.5
        threshold = 8.5
        #threshold = 10.0
        for i, s in enumerate(scores):
            if current_ridge is not None:
                if s < threshold:
                    ridges.append([current_ridge, (i -1)*self.factor])
                    current_ridge = None
            else:
                if s > threshold:
                    current_ridge = i*self.factor
        if current_ridge is not None:
            ridges.append([current_ridge, len(scores)*self.factor])
        min_ridge_length = .13
        ridges[:] = [r for r in ridges if r[1] - r[0] > min_ridge_length]
        return ridges

    def spectrogram(self, title=None):
        #plt.figure(figsize=(6, 3))
        plt.imshow(np.asarray([f for f in self.fft]).T,
                origin='lower', cmap="Greys")
        plt.xticks(plt.xticks()[0], ["{0:.2f}".format(t*self.factor) 
            for t in plt.xticks()[0]])
        plt.xlim(0, len(self.fft))
        
        plt.yticks(plt.yticks()[0], ["{}".format(float('%.2g' % (self.fft_bin_to_frequency(t)/1000.0)))
            for t in plt.yticks()[0]])
        plt.ylim(0,  self.fft_window[1] - self.fft_window[0])

        if title is None:
            plt.title("Processed FFT")
        else:
            plt.title(title)
        plt.xlabel("Time in Seconds")
        plt.ylabel("Frequency in kHz")
        #plt.tight_layout()
        plt.show(block=False)
    
