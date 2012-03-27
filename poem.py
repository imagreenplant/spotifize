#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
--------------------------POEM SPOTIFIZER----------------------------
Code to spotifize a user created poem.

This code implements a form of weighting to sort from the best matches
given from the Spotify Metadata API.

Built on Python 2.7 to allow creation of Django app.  At this time,
Django does not support Python 3.

TODO:
Best Duration


---------------------------------------------------------------------
"""

from __future__ import unicode_literals

try:
    import time
    import threading
    import urllib
    import urllib2
    import sys
    import re
    import Queue
    from xml.etree.cElementTree import ElementTree as XML
    import string
    import logging
except ImportError:
    print "Your system may be missing one of the required libraries for this codebase."
    

SPOTIFY_QUERY_URL = "http://ws.spotify.com/search/1/track?%s"
SPOTIFY_OUTPUT_URL = "http://open.spotify.com/track/%s"        #Insert song token, i.e. href="spotify:track:7Bc0S4rnNF06apWGfK2S3G"
NS = {'sp':"http://www.spotify.com/ns/music/1"}                #Namespace definition for XML parsing

# ----------------------Tweaks --------------------------------------
# There are extra tweaks here that have been commented out.  These would
# be some additional 'sliders' I would implement to improve results depending
# on necessity after testing. """

BEST_EFFORT_DURATION_LIMIT = 20     # Time limit for how long the Poemizer can run 
SPOTIFY_REQ_TIMEOUT = 5             # Timeout to wait for spotify's response
TOTAL_THREADCOUNT = 5               # Total number of threads to use making connections

#Language Weighting
WORD_WEIGHT = 1                   # weight per word in evaluated string
#FULL_LINE = 2                       # string extends to end of line
#FULL_TO_PUNCTUATION = 0.9           # string extends to the nearest punctuation
#STATEMENT = 0.8                     # string has a noun and a verb
#WEIGHT_PER_SYLLABLE = 0.2           # weight per syllable in string
SYLLABIC_CADENCE = 0.6              # string has between 2 and 6 syllables
POPULARITY_WEIGHT_FACTOR = 2        # factor of how much popularity matters
# ------------------------------------------------------------------
    
    
#Setup logging
log = logging.getLogger('spotifize')
log.setLevel( logging.DEBUG )
formatting = logging.Formatter('%(asctime)-6s: - %(levelname)s - %(lineno)d - %(funcName)s - %(threadName)s - %(message)s')
log_handler = logging.StreamHandler()
log_handler.setFormatter(formatting)
log.addHandler( log_handler )
log.info("Initializing Spotifizer")



class Match(dict):

    """
    Object to store one single match, be it one word or longer
    
    A match dictionary is built, and internal calculations to the match
    object calculate the weight or quality of the match based on the
    constants in the Tweaks.
    """
    
    def __init__(self, track_obj ):
        dict.__init__(self)
        self['track'] = track_obj
        self['weight'] = None
        log.debug("Track match object created: %s", track_obj)

    def __weightWordCount(self):
        """Returns weighting for the number of words in a match term"""
        log.info( 'Word weight for %s is %d', self['track']['trackname'], WORD_WEIGHT * len(self['track']['trackname'].split(' ')) )
        return WORD_WEIGHT * len(self['track']['trackname'].split(' ')) #needs to account for line breaks and multiple whitespaces
        
    def __weightCadence(self):
        """
        This is a quick and dirty regex methods to find syllables on the number of vowels.
        
        Most poetic statements contain between 3 and 7 syllables, this weights those that contain that many syllables higher.
        With more time I would look into TeX algorithm if this weighting factor tested as important, as a word like 'house'
            would easily throw off this algorithm.
        """
        
        syllable_number = len( [syl for syl in re.findall(r'[aeiou]+', self['track']['trackname'].lower())  if syl ]  )
        if syllable_number < 8 and syllable_number > 2:
            log.info( "Syllabic weight for %s is %d", self['track']['trackname'], SYLLABIC_CADENCE )
            return SYLLABIC_CADENCE
        else:
            return 0
    
    def __weightPopularity(self):
        """Applies weighting from popularity"""
        try:
            log.info( "Popularity weight for %s is %d", self['track']['trackname'] ,POPULARITY_WEIGHT_FACTOR * float( self['track']['popularity'] ) )
            return POPULARITY_WEIGHT_FACTOR * float( self['track']['popularity'] )
        except ValueError:
            return 0
    
    weighting_functions = (__weightWordCount, __weightCadence, __weightPopularity)
    def __applyWeight(self):
        """Sums and records the overall weighting for this match"""
        self['weight'] = sum( [func(self) for func in self.weighting_functions] )
        
    def __getitem__(self, key):
        """ Overrides key retrieval, and recalculates weighting upon retrieval. """
        if key == 'weight':
            self.__applyWeight()
        return dict.__getitem__(self, key)


class SpotifyPoem(dict):
    
    """store spotify poem metadata, parses itself and adds weighting"""
    def __init__(self, rawpoem = TEST_POEM):
        dict.__init__(self)
        self['original poem'] = rawpoem
        self['matches'] = []
        self['unmatched'] = []
        self['search terms'] = []
        self['wordmap'] = None
        self['location list'] =  None
        self['best matches'] = []
            
    def __addMatch(self, track_object):
        """Add Match objects to the matches list"""
        track_object['exact match'] =  True
        log.info("Exact match found(s): %s", track_object['trackname'] )

        # Instantiate and append new match objects to the master poem list
        self['matches'].append( Match(track_object) )

    
    def match(self, query_data):
        """Looks for string matches provided in file/url object"""
        
        for track in query_data:
            if track['trackname'].lower() == track['query'].lower():
                self.__addMatch(track)
            else:
                self['unmatched'].append( track )
                
    def matchedPrevious(self, query):
        """Function to help dig into old Spotify Metadata request to skim for unused matches that may fit"""
        for track in self['unmatched']:
            log.debug("Testing for previous match.  Query is <%s> and trackname is <%s>", query, track['trackname'])
            if track['trackname'].lower() == query['query'].lower():
                self.__addMatch(track)
                return True
        return False
        # may need to remove from unmatched list, depending on later flow        
                
    def removePunctuation( self, phrase):
        """Remove simple punctuation, but leave apostrophe"""
        return ''.join (re.split(r'[,;!?_-]', phrase) )
                         
    def returnLines(self, text):
        """Split given entry into separate lines."""
        log.debug("Term split by lines: %s", text.splitlines() )
        return [ self.removePunctuation( term.strip() ) for term in text.splitlines() if term ]
        
    def cleanWordSplit(self, phrase):
        """Remove Punctuation and split on lines and whitespace"""
        cleaned_words = []
        for line in phrase.splitlines():
            for word in re.split(r'[ ,;!?_-]', line ):
                if word:
                    cleaned_words.append(word)
        return cleaned_words

    def isUniqueSearchTerm(self, term):
        """Checks for terms already searched for in, to help stem queries to server"""
        if term not in self['search terms']:
            self['search terms'].append(term)
            return True
        else:
            return False
        
    def mapWords(self):
        """Initial mapping or overall poem, to map word locations for correlation later."""
        self['wordmap'] = [ n for n in  self.cleanWordSplit( self['original poem']) if n ]
        self['location list'] = range( 0, len( self['wordmap']) )
        log.info("Word mapping for search string: %s", self['wordmap'])
        log.info("Search term location list: %s", self['location list'])
        
    def getLocations(self, term):
        """Algorithm to determine a given term's location(s) within the overall poem."""
        
        #initiate word map if non-existent
        if not self['wordmap']:
            self.mapWords()
            
        words = [ n.lower() for n in term.split(' ') if n ]
        log.debug("Parsed words for location match(list): %s", words)
        
        locations = []
        if words:
            #Finding the positions of the word queries, to avoid duplication and set multiple locations
            start_positions = [ i for i in range( 0 , len( self['wordmap'] )) if self['wordmap'][i].lower() == words[0].lower() ]
            log.debug("Beginning positions of words in queries: %s", start_positions)
            if start_positions:
                for start_position in start_positions:
                    #If list of words is equal to the same list slice of the wordmap, append to the location map
                    complist1 = [ a.lower() for a in words ]
                    complist2 = [ b.lower() for b in self['wordmap'][ start_position : start_position + len(words) ] ]
                    # The comparison is split into the two phrases above for clarity, and to make sure both are compared lowercase.
                    if complist1 == complist2:
                        log.debug('Found locations %s', range( start_position, start_position + len(words) ) )
                        locations.append( [ j for j in range( start_position, start_position + len(words)) ] )
                        
            return locations         
        return None

    def fillQueue(self, queue):
        """Factory for creation of search terms to be put on queue for processing"""
        # Initialize word mapping
        self.mapWords()
        
        # First we add the entire string to the search queue:
        self.isUniqueSearchTerm( self['original poem'] )
        
        queue.put( { 'query' : self['original poem'].strip(), 'locations' : [self['location list']] })
        
        # Next we will split the original poem by lines
        for line in self.returnLines( self['original poem'] ):
            if self.isUniqueSearchTerm(line):
                log.debug("Line splitting search terms locations, line(string) %s and locations(list) %s", line, self.getLocations(line))
                queue.put( { 'query' : line.strip(), 'locations' : self.getLocations(line) } )
        
        # And finally split by word
        for word in self['wordmap']:
            if self.isUniqueSearchTerm(word):
                log.debug("Word splitting search terms locations, word(string) %s and locations(list) %s", word, self.getLocations(word))
                queue.put( { 'query' : word.strip(), 'locations' : self.getLocations(word) } )
                
        log.debug("Finished filling queue.  Queue is %s", queue.queue )
                
    def getMatchesForLocation(self, location):
        """Returns the matches per word location(s)"""
        
        log.debug("getMatchesForLocation() Location to be found(int): %s", location)
        matched_locations = []
        for match in self['matches']:
            for location_set in match['track']['locations']:
                log.debug("Searching for locations matches, possible location(int) %s, and location set(list) %s" , location , location_set)
                if location in location_set:
                    log.info("Found match %s for this location %s" , match['track']['trackname'], location)
                    matched_locations.append(match)
        return matched_locations
                
    def returnTopLocationMatches(self, matches, amount = 1):
        """Returns the best matches for the location in the amount given."""
        return sorted(matches, key=lambda wght: wght['weight'] , reverse=True )[ 0 : amount ]
    
    def returnPoemMatch(self):
        # Create queue for matching locations.  A found location is then popped off the front of the queue
        # until the while loop stops.
        mqueue = range( 0, len( self['location list'] ))

        ctr = 0
        while mqueue and ctr < 100:
            ctr += 1
            log.debug("Matching queue(list) %s", mqueue)
            best_match = self.returnTopLocationMatches( self.getMatchesForLocation( mqueue[0] ) )
            log.debug("Best match: %s", best_match)
            
            # Removes all locations that the best match comprises
            if best_match:
                try:
                    # Removing the locations from only the best match, to move on
                    for loc in best_match[0]['track']['locations']:
                        if loc[0] == mqueue[0]:
                            [ mqueue.remove(digit) for digit in loc ]
                except ValueError:
                    # Passing here.  Any extra locations removed are not a problem, and we simply move on.
                    pass
                except IndexError:
                    pass
                self['best matches'].extend(best_match)
            else:
                #If no match, move on to next location in queue
                mqueue.pop(0)
            
        log.info("Final poem object %s", self['best matches'])
        return self['best matches']
    
class SpotifyAPI():
    
    """Class for connecting to Spotify API and parsing terms"""

    # tags from Spotify Metadata wanted for later consumption, includes namespaces and path
    tags_wanted = { 'trackname'  : 'sp:name',
                    'album'      : 'sp:album/sp:name',
                    'artist'     : 'sp:artist/sp:name',
                    'popularity' : 'sp:popularity'} 
    
    def __init__(self, poem):
        self.poem = poem

    def parseTrackData(self, spotquery, spotify_metadata):
        """Function for parsing XML response from Spotify"""
        root = XML()
        root.parse(spotify_metadata)
        tracks = root.findall('sp:track', NS)
        
        track_list = []
        for track in tracks:
            track_dict = {'URL' : SPOTIFY_OUTPUT_URL % track.get('href').split(':')[2],
                          'query' : spotquery['query'],
                          'locations' : spotquery['locations'] }
            
            for tag in self.tags_wanted.keys():
                track_dict[ tag ] = track.findtext( self.tags_wanted[tag], None, NS)
            track_list.append(track_dict)
        return track_list
    
    def getTrackMatches(self, spotquery):
        """Main function to grab, parse, and make a call to distribute matches to poem object.
        Currently this only grabs the first page of results.""" 
        request_url = SPOTIFY_QUERY_URL % urllib.urlencode({ 'q' : spotquery[u'query'].encode('utf-8') })
        try:
            track_data = urllib2.urlopen(request_url, None, SPOTIFY_REQ_TIMEOUT)
            log.debug("Header from request %s", track_data.headers.headers)
        except urllib2.URLError:
            log.error("Connection request to Spotify timed out.")
            raise urllib2.URLError

        return self.parseTrackData(spotquery, track_data)
    


class SpotifyConnThread(threading.Thread):
    
    """Creates thread to query Spotify Metadata and parse"""
    
    def __init__(self, spotqueue, poem):
        threading.Thread.__init__(self)
        self.spotqueue = spotqueue
        self.poem = poem
        
    def run(self):
        while True:
            spotquery = self.spotqueue.get()
            
            log.debug("Processing ---%s--- in queue", spotquery)
            
            try:
                #Search previous matches, and if nothing, connect to Spotify for search
                if not self.poem.matchedPrevious(spotquery):
                    self.poem.match( SpotifyAPI( self.poem ).getTrackMatches( spotquery ))
            except Exception, e:
                log.exception("Exception in thread, %s", e)
            finally:
                self.spotqueue.task_done()

class TimeoutError(Exception):
    """Defines Timeout error is best effort duration is reached."""
    def __init__(self):
        self.duration = BEST_EFFORT_DURATION_LIMIT
        
class SpotifizePoem():
    
    """Main controller class for taking a poem and creating a Spotify playlist"""
    
    def __init__(self, poem_text):
        self.poem_text = poem_text
        
    def getRawPoemInput(self):
        """Get poem input"""
        return self.poem_text
    
    def spotifize(self):
        """Runs the poem spotifizer"""

        start_time = time.time()
        log.info("Start time is %s", start_time)
        
        try:
            #initiate threading queue
            queue = Queue.Queue()
            
            poem = SpotifyPoem(self.getRawPoemInput())
            
            #Fill queue with search terms from poem
            poem.fillQueue(queue)
            
            #spawn threads
            for j in range( TOTAL_THREADCOUNT ):
                log.debug("Creating thread %s", j)
                thr = SpotifyConnThread( queue, poem )
                thr.setDaemon(True)
                thr.start()
    
            #process queue
            queue.join()
            
            log.info("Spotifized in %s secs" % (time.time() - start_time) )
            
            #sort best output data
            return poem.returnPoemMatch()
        
        except KeyboardInterrupt:
            sys.exit()
            
        except 
            
    def printBestMatches(self):
        for item in self.spotifize():
            print "---------------------" + item['track']['query'] + "---------------------------"
            print item['track']['trackname'] + " by " + item['track']['artist'] + " --> " + item['track']['URL']
            

if __name__ == '__main__':
    import argparse
    
    log.debug("Using command line interface.")
    ver = sys.version_info
    if ver.major != 2 or ver.minor != 7:
        print "This code was built on Python 2.7, and running under other versions may cause problems. \
            Other version are currently untested."
    
    parser = argparse.ArgumentParser(description='Spotifize text from a poem.')
    group = parser.add_mutually_exclusive_group(required = True)
    group.add_argument('-f', '--file', help = "Input a filename with the poem text")
    group.add_argument('-t', '--text', help = "Input raw text at the command line")
    args = parser.parse_args()
    log.debug("Commandline argruments: %s" , repr(args) )
    
    if args.file:
        f = open( args.file, 'r')
        rawpoem = f.read()
    elif args.text:
        rawpoem = args.text

    spotifizer = SpotifizePoem( rawpoem.decode('utf-8') )
    spotifizer.printBestMatches()

    

    
"""
Things to Improve with More Time:
- More intelligent Algorithm to determine more 'human-ish' poetry entries, as in better semantic structure
- Research more Exceptions to protect the program
- Do more taste testing of the results with other people
- Allow for more fuzzy terms, like searching for "I am" when "I'm" is inputted
- Also fuzzy the number of words, breaking a 3 word line into 5 possibilities, instead of 3
- Match subsets from same API request, instead of making a second request
- Do second queue for putting new search items up for processing
- For suggestions in the case of no match, would use Levenshtein library for word similarity
- account for searches with an apostrophe, matching "I'm" and "Im" or "Let's" and "Lets"
"""
 



    
    